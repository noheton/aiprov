"""Bulk telemetry tier: a hash-chained JSONL file whose head the graph records (issue 15)."""
import json, subprocess, sys

BASE = "https://example.org/prov/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def ok(args, cwd):
    r = run(args, cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def bad(args, cwd):
    r = run(args, cwd)
    assert r.returncode != 0, r.stdout
    return r


def setup(tmp_path):
    ok(["init"], tmp_path)
    ok(["agent", "--id", "gw", "--type", "ai", "--model", "m-1"], tmp_path)


def add(tmp_path, n, name="tel.jsonl", start=0, marker=None):
    for i in range(start, start + n):
        d = {"req": i, "tokens": 10 * i}
        if marker:
            d["marker"] = marker
        ok(["bulk", "append", "--file", name, "--data", json.dumps(d)], tmp_path)


def test_append_builds_a_chain_and_verify_names_the_head(tmp_path):
    setup(tmp_path)
    add(tmp_path, 3)
    recs = [json.loads(x) for x in (tmp_path / "tel.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["seq"] for r in recs] == [1, 2, 3]
    assert recs[0]["prev"] == "sha256:" + "0" * 64 and recs[1]["prev"] == recs[0]["hash"]
    out = ok(["bulk", "verify", "--file", "tel.jsonl"], tmp_path).stdout
    assert "3 records" in out and recs[2]["hash"] in out


def test_a_changed_or_removed_record_breaks_the_chain(tmp_path):
    setup(tmp_path)
    add(tmp_path, 3)
    f = tmp_path / "tel.jsonl"
    text = f.read_text(encoding="utf-8")
    f.write_text(text.replace('"tokens":10', '"tokens":99'), encoding="utf-8")
    assert "line 2" in (bad(["bulk", "verify", "--file", "tel.jsonl"], tmp_path).stderr)
    f.write_text("".join(text.splitlines(True)[1:]), encoding="utf-8")      # first record removed
    assert "line 1" in (bad(["bulk", "verify", "--file", "tel.jsonl"], tmp_path).stderr)
    lines = text.splitlines(True)
    f.write_text(lines[0] + lines[2] + lines[1], encoding="utf-8")           # reordered
    assert "line 2" in (bad(["bulk", "verify", "--file", "tel.jsonl"], tmp_path).stderr)


def test_anchor_holds_while_the_file_grows_and_finds_a_different_chain(tmp_path):
    setup(tmp_path)
    add(tmp_path, 2)
    ok(["bulk", "anchor", "--id", "c1", "--file", "tel.jsonl", "--agent", "gw"], tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    add(tmp_path, 2, start=2)
    out = ok(["bulk", "verify", "--file", "tel.jsonl", "--anchor", "c1"], tmp_path).stdout
    assert "first 2 records match" in out and "2 appended since" in out
    add(tmp_path, 2, name="other.jsonl", start=5)                              # a valid chain, but another one
    assert "differs" in bad(["bulk", "verify", "--file", "other.jsonl", "--anchor", "c1"], tmp_path).stderr
    add(tmp_path, 1, name="short.jsonl")
    assert "missing" in bad(["bulk", "verify", "--file", "short.jsonl", "--anchor", "c1"], tmp_path).stderr
    assert "not a telemetry chain" in bad(["bulk", "verify", "--file", "tel.jsonl", "--anchor", "nope"], tmp_path).stderr


def test_the_graph_holds_the_head_and_the_length_never_a_record(tmp_path):
    setup(tmp_path)
    add(tmp_path, 3, marker="zzq-payload")
    ok(["bulk", "anchor", "--id", "c1", "--file", "tel.jsonl", "--agent", "gw", "--upto", "2"], tmp_path)
    ttl = (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    head2 = json.loads((tmp_path / "tel.jsonl").read_text(encoding="utf-8").splitlines()[1])["hash"]
    assert head2 in ttl and "zzq-payload" not in ttl and "chainLength" in ttl
    assert "1 records" not in ok(["report"], tmp_path).stdout and "2 records, head " + head2 in ok(["report"], tmp_path).stdout
    f = tmp_path / "provenance.ttl"
    f.write_text(ttl.replace(head2, "not-a-hash"), encoding="utf-8")
    r = bad(["validate"], tmp_path)
    assert "telemetry chain anchors" in r.stdout and "FAIL" in r.stdout


def test_refusals(tmp_path):
    setup(tmp_path)
    bad(["bulk", "append", "--file", "t.jsonl"], tmp_path)                                  # no data
    bad(["bulk", "append", "--file", "t.jsonl", "--data", "[1]"], tmp_path)                 # not an object
    bad(["bulk", "append", "--file", "t.jsonl", "--data", "{oops"], tmp_path)               # not JSON
    assert not (tmp_path / "t.jsonl").exists()                                              # nothing written on refusal
    (tmp_path / "d.json").write_text('{"a": 1}', encoding="utf-8")
    ok(["bulk", "append", "--file", "t.jsonl", "--data-file", "d.json"], tmp_path)
    bad(["bulk", "anchor", "--id", "c1", "--file", "t.jsonl", "--agent", "ghost"], tmp_path)  # unregistered
    bad(["bulk", "anchor", "--id", "c1", "--file", "t.jsonl"], tmp_path)                    # no agent
    bad(["bulk", "anchor", "--id", "c1", "--file", "t.jsonl", "--agent", "gw", "--upto", "5"], tmp_path)
    ok(["bulk", "anchor", "--id", "c1", "--file", "t.jsonl", "--agent", "gw"], tmp_path)
    assert "already logged" in bad(["bulk", "anchor", "--id", "c1", "--file", "t.jsonl", "--agent", "gw"], tmp_path).stderr
    with open(tmp_path / "t.jsonl", "ab") as fh:                                            # a torn last line
        fh.write(b'{"seq":2')
    assert "incomplete" in bad(["bulk", "append", "--file", "t.jsonl", "--data", "{}"], tmp_path).stderr
    bad(["bulk", "anchor", "--id", "c2", "--file", "t.jsonl", "--agent", "gw"], tmp_path)    # broken chain


def test_graph_without_chains_is_unchanged(tmp_path):
    setup(tmp_path)
    out = ok(["validate"], tmp_path).stdout
    assert "telemetry chain anchors" in out and "0" in out.split("telemetry chain anchors")[1].splitlines()[0]
