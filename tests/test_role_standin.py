"""Role stand-ins and omitted counts (issue 12)."""
import os
import pathlib
import shutil
import subprocess
import sys

from rdflib import RDF, Graph, Literal, Namespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "example-graph.ttl"
BAD = ROOT / "tests" / "fixtures" / "standin-bad.ttl"
BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "PROV_ACTOR": ""}, check=False)


def graph(tmp_path):
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    return tmp_path / "provenance.ttl"


def load(ttl):
    g = Graph(); g.parse(ttl, format="turtle")
    return g


def out(r):
    return r.stdout + r.stderr


def test_a_role_stand_in_is_registered_with_its_role(tmp_path):
    ttl = graph(tmp_path)
    r = run(["agent", "--id", "requester-1", "--type", "role", "--role", "requester"], tmp_path)
    assert r.returncode == 0, out(r)
    g = load(ttl)
    node = next(s for s in g.subjects(RDF.type, AIPROV.RoleStandIn) if str(s).endswith("requester-1"))
    assert list(g.objects(node, AIPROV.role)) == [Literal("requester")]
    assert run(["validate"], tmp_path).returncode == 0


def test_a_stand_in_needs_a_role_and_carries_no_model_or_person_data(tmp_path):
    ttl = graph(tmp_path)
    before = ttl.read_bytes()
    for args in (["--type", "role"], ["--type", "role", "--role", "r", "--model", "m"],
                 ["--type", "role", "--role", "r", "--orcid", "0000"], ["--type", "ai", "--role", "r"]):
        r = run(["agent", "--id", "x-1", *args], tmp_path)
        assert r.returncode != 0 and "REFUSED" in out(r), (args, out(r))
    assert ttl.read_bytes() == before


def test_a_stand_in_cannot_become_another_type_and_the_other_way_round(tmp_path):
    ttl = graph(tmp_path)
    assert run(["agent", "--id", "rev-1", "--type", "role", "--role", "reviewer"], tmp_path).returncode == 0
    before = ttl.read_bytes()
    for t in ("human", "ai", "tool"):
        r = run(["agent", "--id", "rev-1", "--type", t], tmp_path)
        assert r.returncode != 0 and "REFUSED" in out(r), (t, out(r))
    r = run(["agent", "--id", "model-x", "--type", "role", "--role", "reviewer"], tmp_path)
    assert r.returncode != 0 and "REFUSED" in out(r)
    assert ttl.read_bytes() == before


def test_a_stand_in_can_never_grant_a_human_only_rung(tmp_path):
    ttl = graph(tmp_path)
    assert run(["agent", "--id", "rev-1", "--type", "role", "--role", "reviewer"], tmp_path).returncode == 0
    before = ttl.read_bytes()
    r = run(["claim", "--id", "c-standin", "--text", "x", "--parent", "draft-1", "--agent", "rev-1",
             "--state", "human-read"], tmp_path)
    assert r.returncode != 0 and "human-only" in out(r)
    assert ttl.read_bytes() == before
    assert run(["claim", "--id", "c-standin", "--text", "x", "--parent", "draft-1", "--agent", "rev-1",
                "--state", "unverified"], tmp_path).returncode == 0
    before = ttl.read_bytes()
    r = run(["promote", "--id", "c-standin", "--to", "human-confirmed", "--agent", "rev-1"], tmp_path)
    assert r.returncode != 0 and "human-only" in out(r)
    assert ttl.read_bytes() == before


def test_a_stand_in_can_author_and_be_logged_like_any_agent(tmp_path):
    graph(tmp_path)
    assert run(["agent", "--id", "rev-1", "--type", "role", "--role", "reviewer"], tmp_path).returncode == 0
    r = run(["log", "--activity", "review-mr-7", "--pass", "audit", "--agent", "rev-1", "--label", "review"], tmp_path)
    assert r.returncode == 0, out(r)
    c = run(["claim", "--id", "c-ok", "--text", "x", "--parent", "review-mr-7", "--agent", "rev-1",
             "--state", "unverified"], tmp_path)
    assert c.returncode == 0, out(c)
    assert run(["validate"], tmp_path).returncode == 0


def test_omitted_count_is_stored_as_an_integer_and_refused_when_not_one(tmp_path):
    ttl = graph(tmp_path)
    r = run(["log", "--activity", "big-change", "--omitted-count", "42", "--label", "large change"], tmp_path)
    assert r.returncode == 0, out(r)
    g = load(ttl)
    vals = [o for _, o in g.subject_objects(AIPROV.omittedCount)]
    assert [v.toPython() for v in vals] == [42]
    before = ttl.read_bytes()
    for bad in ("-1", "many", "1.5"):
        r = run(["log", "--activity", "bad-" + bad.replace(".", "-"), "--omitted-count", bad], tmp_path)
        assert r.returncode != 0 and "omitted-count" in out(r), (bad, out(r))
    assert ttl.read_bytes() == before


def test_validate_fails_mixed_stand_ins_stand_in_rungs_and_bad_counts(tmp_path):
    ttl = graph(tmp_path)
    with ttl.open("a") as f:
        f.write("\n" + BAD.read_text())
    r = run(["validate"], tmp_path)
    text = out(r)
    assert r.returncode != 0
    assert "role stand-ins also typed as a person, AI agent or tool: 1" in text
    assert "human-only rungs granted by role stand-ins: 1" in text
    assert "omitted counts that are not a non-negative integer: 2" in text


def test_graphs_without_stand_ins_validate_unchanged(tmp_path):
    graph(tmp_path)
    r = run(["validate"], tmp_path)
    assert r.returncode == 0 and "role stand-ins also typed as a person, AI agent or tool: 0" in out(r)
