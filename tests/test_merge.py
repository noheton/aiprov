"""Sharded logging: each agent writes into its own copy of the graph; the dispatcher merges."""
import pathlib, shutil, subprocess, sys

BASE = "https://example.org/prov/"
A = BASE + "agent/"; ACT = BASE + "activity/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def ok(args, cwd):
    r = run(args, cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def main_graph(tmp_path):
    ok(["init"], tmp_path)
    for w in ("orch", "rev1", "rev2", "verifier", "stray"):
        ok(["agent", "--id", w, "--type", "ai", "--model", "m"], tmp_path)
    ok(["log", "--activity", "o1", "--orchestration", "--agent", "orch", "--planned-agent", "rev1",
        "--planned-agent", "rev2", "--planned-agent", "verifier", "--planned-role", "review",
        "--planned-role", "verify"], tmp_path)
    return tmp_path


def shard(main, name):
    d = main / "shards" / name
    d.mkdir(parents=True)
    shutil.copy(main / "provenance.ttl", d / "provenance.ttl")
    return d


def test_two_shards_merge_and_validate(tmp_path):
    m = main_graph(tmp_path)
    for name in ("rev1", "rev2"):
        d = shard(m, name)
        ok(["log", "--activity", f"s-{name}", "--informed-by", "o1", "--agent", name, "--role", "review"], d)
        ok(["claim", "--id", f"c-{name}", "--parent", f"s-{name}", "--agent", name, "--text", "a finding"], d)
    r = ok(["merge", "--from", str(m / "shards/rev1/provenance.ttl"), str(m / "shards/rev2/provenance.ttl")], m)
    assert r.stdout.count("merged") == 2
    assert ok(["validate"], m).returncode == 0
    rep = ok(["report"], m).stdout
    assert "2 sub-activities" in rep


def test_promotion_in_a_second_shard_leaves_one_state(tmp_path):
    m = main_graph(tmp_path)
    d1 = shard(m, "rev1")
    ok(["log", "--activity", "s1", "--informed-by", "o1", "--agent", "rev1", "--role", "review"], d1)
    ok(["claim", "--id", "c1", "--parent", "s1", "--agent", "rev1", "--text", "a finding"], d1)
    d2 = shard(m, "verifier")
    shutil.copy(d1 / "provenance.ttl", d2 / "provenance.ttl")
    ok(["promote", "--id", "c1", "--to", "ai-confirmed", "--agent", "verifier"], d2)
    ok(["merge", "--from", str(d1 / "provenance.ttl"), str(d2 / "provenance.ttl")], m)
    from rdflib import Graph, URIRef
    g = Graph(); g.parse(m / "provenance.ttl", format="turtle")
    states = list(g.objects(URIRef(BASE + "claim/c1"), URIRef("https://w3id.org/aiprov/ns#verificationState")))
    assert [str(s) for s in states] == [BASE + "verification/ai-confirmed"]


def test_shard_cannot_widen_a_frozen_plan(tmp_path):
    m = main_graph(tmp_path)
    d = shard(m, "stray")
    with open(d / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f"<{ACT}o1> <https://w3id.org/aiprov/ns#plannedAgent> <{A}stray> .\n")
    ok(["log", "--activity", "s-stray", "--informed-by", "o1", "--agent", "stray", "--role", "review"], d)
    before = (m / "provenance.ttl").read_text(encoding="utf-8")
    r = run(["merge", "--from", str(d / "provenance.ttl")], m)
    assert r.returncode == 1 and "frozen plan" in r.stdout
    assert (m / "provenance.ttl").read_text(encoding="utf-8") == before


def test_shard_that_breaks_validation_is_rejected_others_still_merge(tmp_path):
    m = main_graph(tmp_path)
    good = shard(m, "rev1")
    ok(["log", "--activity", "s1", "--informed-by", "o1", "--agent", "rev1", "--role", "review"], good)
    bad = shard(m, "rev2")
    with open(bad / "provenance.ttl", "a", encoding="utf-8") as f:   # hand-edited: agent outside the plan
        f.write(f"<{ACT}evil> a <https://w3id.org/aiprov/ns#AuthoringPass> ; "
                f"<http://www.w3.org/ns/prov#endedAtTime> \"2999-01-01T00:00:00+00:00\"^^<http://www.w3.org/2001/XMLSchema#dateTime> ; "
                f"<http://www.w3.org/ns/prov#wasInformedBy> <{ACT}o1> ; "
                f"<http://www.w3.org/ns/prov#wasAssociatedWith> <{A}stray> ; "
                f"<https://w3id.org/aiprov/ns#role> \"review\" .\n")
    r = run(["merge", "--from", str(good / "provenance.ttl"), str(bad / "provenance.ttl")], m)
    assert r.returncode == 1 and "REJECTED" in r.stdout and "outside the orchestration plan" in r.stdout
    assert "activity/s1" in (m / "provenance.ttl").read_text(encoding="utf-8")
    assert "activity/evil" not in (m / "provenance.ttl").read_text(encoding="utf-8")
