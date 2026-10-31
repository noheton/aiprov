"""An agent is an AI or a person, never both; self-registration leaves a trace; refusals can be recorded (issue 22)."""
import os
import pathlib
import shutil
import subprocess
import sys

from rdflib import RDF, Graph, Namespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "example-graph.ttl"
DUAL = ROOT / "tests" / "fixtures" / "dual-typed-agent.ttl"
BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")


def run(args, cwd, actor=""):
    env = {**os.environ, "PROV_ACTOR": actor}
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env=env, check=False)


def graph(tmp_path):
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    return tmp_path / "provenance.ttl"


def load(ttl):
    g = Graph(); g.parse(ttl, format="turtle")
    return g


def test_ai_agent_cannot_become_a_person_and_the_graph_is_unchanged(tmp_path):
    ttl = graph(tmp_path)
    before = ttl.read_bytes()
    r = run(["agent", "--id", "model-x", "--type", "human"], tmp_path)
    assert r.returncode != 0 and "REFUSED" in r.stdout + r.stderr
    assert ttl.read_bytes() == before


def test_person_cannot_become_an_ai_agent(tmp_path):
    ttl = graph(tmp_path)
    assert run(["agent", "--id", "person-y", "--type", "human", "--name", "P"], tmp_path).returncode == 0
    before = ttl.read_bytes()
    r = run(["agent", "--id", "person-y", "--type", "ai", "--model", "m"], tmp_path)
    assert r.returncode != 0 and "REFUSED" in r.stdout + r.stderr
    assert ttl.read_bytes() == before


def test_registration_of_a_person_records_who_and_when_once(tmp_path):
    ttl = graph(tmp_path)
    assert run(["agent", "--id", "boss", "--type", "human"], tmp_path).returncode == 0
    assert run(["agent", "--id", "person-y", "--type", "human", "--by", "boss"], tmp_path).returncode == 0
    first = load(ttl)
    node = next(s for s in first.subjects(RDF.type, AIPROV.HumanAgent) if str(s).endswith("person-y"))
    assert [str(o).endswith("boss") for o in first.objects(node, AIPROV.registeredBy)] == [True]
    assert len(list(first.objects(node, AIPROV.registeredAtTime))) == 1
    assert run(["agent", "--id", "person-y", "--type", "human", "--by", "boss"], tmp_path).returncode == 0
    again = load(ttl)
    assert len(list(again.objects(node, AIPROV.registeredAtTime))) == 1


def test_actor_variable_is_the_default_for_by(tmp_path):
    ttl = graph(tmp_path)
    assert run(["agent", "--id", "person-y", "--type", "human"], tmp_path, actor="tool-z").returncode == 0
    g = load(ttl)
    node = next(s for s in g.subjects(RDF.type, AIPROV.HumanAgent) if str(s).endswith("person-y"))
    assert [str(o).endswith("tool-z") for o in g.objects(node, AIPROV.registeredBy)] == [True]


def test_validate_fails_a_dual_typed_node_and_names_it(tmp_path):
    ttl = tmp_path / "provenance.ttl"
    shutil.copy(DUAL, ttl)
    r = run(["validate"], tmp_path)
    assert r.returncode != 0
    assert "agents typed as both AI and human: 1" in r.stdout and "model-z" in r.stdout


def test_refusal_leaves_the_graph_unchanged_by_default(tmp_path):
    ttl = graph(tmp_path)
    before = ttl.read_bytes()
    r = run(["claim", "--id", "c1", "--text", "t", "--parent", "draft-1", "--agent", "model-x",
             "--state", "human-read"], tmp_path)
    assert r.returncode != 0
    assert ttl.read_bytes() == before


def test_record_refusals_writes_one_refusal_and_nothing_else(tmp_path):
    ttl = graph(tmp_path)
    before = load(ttl)
    r = run(["claim", "--id", "c1", "--text", "t", "--parent", "draft-1", "--agent", "model-x",
             "--state", "human-read", "--record-refusals"], tmp_path)
    assert r.returncode != 0 and "REFUSED" in r.stdout + r.stderr
    after = load(ttl)
    refusals = list(after.subjects(RDF.type, AIPROV.Refusal))
    assert len(refusals) == 1
    node = refusals[0]
    new = set(after) - set(before)
    assert not (set(before) - set(after))
    assert {s for s, _, _ in new} == {node}
    assert str(next(after.objects(node, AIPROV.refusedStep))) == "claim"
    assert str(next(after.objects(node, AIPROV.refusedTarget))) == "c1"
    assert str(next(after.objects(node, AIPROV.refusedRung))) == "human-read"
    assert run(["validate"], tmp_path).returncode == 0
    assert "refusals:           1" in run(["report"], tmp_path).stdout


def test_record_refusals_for_promote_and_source(tmp_path):
    ttl = graph(tmp_path)
    r = run(["source", "--id", "s1", "--url", "https://example.org/x", "--state", "human-read",
             "--agent", "model-x", "--record-refusals"], tmp_path)
    assert r.returncode != 0
    g = load(ttl)
    assert len(list(g.subjects(RDF.type, AIPROV.Refusal))) == 1
    assert not list(g.subjects(RDF.type, AIPROV.Source)) or all("s1" not in str(s) for s in g.subjects(RDF.type, AIPROV.Source))
