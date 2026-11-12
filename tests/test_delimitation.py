"""Novelty claims as a delimitation record, never a score (issue 16)."""
import pathlib, subprocess, sys

BASE = "https://example.org/prov/"
HASH = "sha256:" + "a" * 64


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def ok(args, cwd):
    r = run(args, cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def setup(tmp_path):
    ok(["init"], tmp_path)
    ok(["agent", "--id", "writer", "--type", "ai", "--model", "m-1"], tmp_path)
    ok(["log", "--activity", "draft", "--agent", "writer"], tmp_path)
    ok(["claim", "--id", "n1", "--text", "No prior work does X.", "--parent", "draft", "--agent", "writer",
        "--kind", "novelty"], tmp_path)
    ok(["claim", "--id", "n2", "--text", "No prior work does Y.", "--parent", "draft", "--agent", "writer",
        "--kind", "novelty"], tmp_path)
    ok(["claim", "--id", "e1", "--text", "X runs in 3 s.", "--parent", "draft", "--agent", "writer",
        "--kind", "empirical"], tmp_path)


def record(tmp_path, claim="n1", rec="d1"):
    return ["delimitation", "--id", rec, "--claim", claim, "--agent", "writer", "--query", "x AND y",
            "--searched-in", "Index A", "--searched-on", "2026-10-30", "--result-hash", HASH,
            "--nearest", "10.1234/abc=Handles Z, not X"]


def test_documented_and_undocumented_are_told_apart(tmp_path):
    setup(tmp_path)
    ok(record(tmp_path), tmp_path)
    out = ok(["validate"], tmp_path).stdout
    assert "novelty claims: 2 (delimitation documented 1, not documented 1)" in out
    assert "novelty claims:     2 (delimitation documented 1, not documented 1)" in ok(["report"], tmp_path).stdout


def test_undocumented_novelty_claim_at_a_low_rung_is_a_state_not_an_error(tmp_path):
    setup(tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0


def test_no_start_at_ai_confirmed_without_a_record(tmp_path):
    setup(tmp_path)
    r = run(["claim", "--id", "n3", "--text", "No prior work does W.", "--parent", "draft", "--agent", "writer",
             "--kind", "novelty", "--state", "ai-confirmed"], tmp_path)
    assert r.returncode != 0 and "delimitation record" in r.stdout + r.stderr
    assert "n3" not in (tmp_path / "provenance.ttl").read_text(encoding="utf-8")


def test_validate_fails_a_novelty_claim_raised_without_a_record(tmp_path):
    setup(tmp_path)
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f"\n<{BASE}claim/n2> <https://w3id.org/aiprov/ns#verificationState> <{BASE}verification/ai-confirmed> .\n")
    r = run(["validate"], tmp_path)
    assert r.returncode != 0 and "without a delimitation record" in r.stdout


def test_record_needs_a_novelty_claim_and_complete_input(tmp_path):
    setup(tmp_path)
    assert run(record(tmp_path, claim="e1"), tmp_path).returncode != 0          # not of kind novelty
    assert run(record(tmp_path, claim="nope"), tmp_path).returncode != 0         # no such claim
    bad = record(tmp_path)
    bad[bad.index(HASH)] = "abc"
    assert run(bad, tmp_path).returncode != 0                                    # not a sha256
    no_near = [x for x in record(tmp_path)][:-2]
    assert run(no_near, tmp_path).returncode != 0                                # no nearest work
    ok(record(tmp_path), tmp_path)
    assert run(record(tmp_path), tmp_path).returncode != 0                       # append-only


def test_unfinished_record_fails_validate(tmp_path):
    setup(tmp_path)
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f"\n<{BASE}delimitation/bare> a <https://w3id.org/aiprov/ns#DelimitationRecord> ;"
                f" <https://w3id.org/aiprov/ns#delimits> <{BASE}claim/n1> .\n")
    r = run(["validate"], tmp_path)
    assert r.returncode != 0 and "without search protocol or nearest works" in r.stdout


def test_no_numeric_novelty_attribute_exists(tmp_path):
    schema = (pathlib.Path(__file__).resolve().parent.parent / "schema" / "aiprov-schema.ttl").read_text(encoding="utf-8")
    for line in schema.splitlines():
        head = line.split(" ", 1)[0].lower()
        if line.startswith("aiprov:") and ("novelty" in head or "originality" in head or head.endswith("score")):
            assert "xsd:integer" not in line and "xsd:decimal" not in line and "xsd:double" not in line, line
    setup(tmp_path)
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f'\n<{BASE}claim/n1> <https://w3id.org/aiprov/ns#noveltyScore> 0.9 .\n')
    r = run(["validate"], tmp_path)
    assert r.returncode != 0 and "numeric novelty" in r.stdout


def test_limitation_is_stated_in_validate_and_report(tmp_path):
    setup(tmp_path)
    for out in (ok(["validate"], tmp_path).stdout, ok(["report"], tmp_path).stdout):
        assert "not that the claim is new" in out


def test_no_limitation_line_without_novelty_claims(tmp_path):
    ok(["init"], tmp_path)
    assert "not that the claim is new" not in ok(["validate"], tmp_path).stdout
    assert "not that the claim is new" not in ok(["report"], tmp_path).stdout
