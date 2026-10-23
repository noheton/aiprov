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


# --- hardening after the second multi-agent review ---------------------------------------------

AI = "https://w3id.org/aiprov/ns#"
PROVNS = "http://www.w3.org/ns/prov#"


def append(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def test_fixing_one_failure_and_adding_another_is_still_a_regression(tmp_path):
    m = main_graph(tmp_path)
    append(m / "provenance.ttl", f"<{BASE}claim/p1> a <{AI}Claim> ; <{PROVNS}wasAttributedTo> <{A}orch> .\n")
    d = shard(m, "swap")
    append(d / "provenance.ttl", f"<{BASE}claim/p2> a <{AI}Claim> ; <{PROVNS}wasAttributedTo> <{A}orch> .\n"
                                 f"<{BASE}claim/p1> <{PROVNS}wasGeneratedBy> <{ACT}o1> .\n")
    r = run(["merge", "--from", str(d / "provenance.ttl")], m)
    assert r.returncode == 1 and "REJECTED" in r.stdout and "claim/p2" in r.stdout


def test_unreadable_shard_is_rejected_not_a_traceback(tmp_path):
    m = main_graph(tmp_path)
    good = shard(m, "rev1")
    ok(["log", "--activity", "s1", "--informed-by", "o1", "--agent", "rev1", "--role", "review"], good)
    junk = m / "junk.ttl"; junk.write_text("this is not turtle {{{", encoding="utf-8")
    r = run(["merge", "--from", str(junk), str(good / "provenance.ttl"), str(m / "missing.ttl")], m)
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert r.stdout.count("REJECTED") == 2 and "unreadable shard" in r.stdout and "merged" in r.stdout


def test_blank_nodes_in_the_main_graph_are_named_as_the_cause(tmp_path):
    m = main_graph(tmp_path)
    append(m / "provenance.ttl", f"[] a <{PROVNS}Entity> .\n")
    r = run(["merge", "--from", str(m / "provenance.ttl")], m)
    assert r.returncode != 0 and "main graph contains blank nodes" in (r.stdout + r.stderr)


def test_demotion_is_refused_and_non_ladder_states_are_kept(tmp_path):
    from rdflib import Graph, URIRef
    m = main_graph(tmp_path)
    ok(["log", "--activity", "w1", "--agent", "orch"], m)
    ok(["claim", "--id", "c1", "--parent", "w1", "--agent", "orch", "--text", "x", "--state", "ai-confirmed"], m)
    claim, st = URIRef(BASE + "claim/c1"), URIRef(AI + "verificationState")
    down = shard(m, "down"); g = Graph(); g.parse(down / "provenance.ttl", format="turtle")
    g.remove((claim, st, None)); g.add((claim, st, URIRef(BASE + "verification/needs-research")))
    g.serialize(down / "provenance.ttl", format="turtle")
    r = run(["merge", "--from", str(down / "provenance.ttl")], m)
    assert r.returncode == 1 and "demotes" in r.stdout
    flag = shard(m, "flag"); append(flag / "provenance.ttl", f"<{BASE}claim/c1> <{AI}verificationState> <{BASE}verification/contested> .\n")
    ok(["merge", "--from", str(flag / "provenance.ttl")], m)
    g = Graph(); g.parse(m / "provenance.ttl", format="turtle")
    assert {str(o).rsplit("/", 1)[-1] for o in g.objects(claim, st)} == {"ai-confirmed", "contested"}


def test_a_bare_human_rung_in_a_shard_is_refused(tmp_path):
    m = main_graph(tmp_path)
    ok(["log", "--activity", "w1", "--agent", "orch"], m)
    ok(["claim", "--id", "c1", "--parent", "w1", "--agent", "orch", "--text", "x"], m)
    d = shard(m, "forge")
    append(d / "provenance.ttl", f"<{BASE}claim/c1> <{AI}verificationState> <{BASE}verification/human-confirmed> .\n")
    r = run(["merge", "--from", str(d / "provenance.ttl")], m)
    assert r.returncode == 1 and "human-only rung without human promotion" in r.stdout


def test_retyping_an_existing_node_as_orchestration_is_refused(tmp_path):
    m = main_graph(tmp_path)
    ok(["log", "--activity", "w1", "--agent", "orch"], m)
    d = shard(m, "retype")
    append(d / "provenance.ttl", f"<{ACT}w1> a <{AI}Orchestration> .\n")
    r = run(["merge", "--from", str(d / "provenance.ttl")], m)
    assert r.returncode == 1 and "retypes the existing node w1" in r.stdout


def test_shard_order_does_not_matter(tmp_path):
    from rdflib import Graph, URIRef
    m = main_graph(tmp_path)
    d1 = shard(m, "rev1")
    ok(["log", "--activity", "s1", "--informed-by", "o1", "--agent", "rev1", "--role", "review"], d1)
    ok(["claim", "--id", "c1", "--parent", "s1", "--agent", "rev1", "--text", "a finding"], d1)
    d2 = shard(m, "verifier"); shutil.copy(d1 / "provenance.ttl", d2 / "provenance.ttl")
    ok(["promote", "--id", "c1", "--to", "ai-confirmed", "--agent", "verifier"], d2)
    r = run(["merge", "--from", str(d2 / "provenance.ttl"), str(d1 / "provenance.ttl")], m)  # promoted copy first
    assert r.returncode == 0, r.stdout + r.stderr
    g = Graph(); g.parse(m / "provenance.ttl", format="turtle")
    assert [str(s).rsplit("/", 1)[-1] for s in g.objects(URIRef(BASE + "claim/c1"), URIRef(AI + "verificationState"))] == ["ai-confirmed"]


def test_planned_binding_ties_an_agent_to_its_role(tmp_path):
    ok(["init"], tmp_path)
    for w in ("orch", "rev1", "verifier"):
        ok(["agent", "--id", w, "--type", "ai", "--model", "m"], tmp_path)
    ok(["log", "--activity", "o1", "--orchestration", "--agent", "orch",
        "--planned-agent", "rev1:review", "--planned-agent", "verifier:verify"], tmp_path)
    r = run(["log", "--activity", "x", "--informed-by", "o1", "--agent", "rev1", "--role", "verify"], tmp_path)
    assert r.returncode != 0 and "is bound to role(s) review, not verify" in (r.stdout + r.stderr)
    ok(["log", "--activity", "ok1", "--informed-by", "o1", "--agent", "rev1", "--role", "review"], tmp_path)
    ok(["log", "--activity", "ok2", "--informed-by", "o1", "--agent", "verifier", "--role", "verify"], tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    # the same violation in a hand-edited graph is caught by validate
    append(tmp_path / "provenance.ttl", f"<{ACT}evil> a <{AI}AuthoringPass> ; <{PROVNS}endedAtTime> "
           f"\"2999-01-01T00:00:00+00:00\"^^<http://www.w3.org/2001/XMLSchema#dateTime> ; <{PROVNS}wasInformedBy> <{ACT}o1> ; "
           f"<{PROVNS}wasAssociatedWith> <{A}rev1> ; <{AI}role> \"verify\" .\n")
    v = run(["validate"], tmp_path)
    assert v.returncode == 1 and "[FAIL] sub-activities outside the orchestration plan" in v.stdout
