"""Human-only steps are refused by every command that sets a verification state (issue 18)."""
import pathlib, shutil, subprocess, sys
from rdflib import Graph, URIRef

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "example-graph.ttl"
BASE = "https://example.org/prov/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def graph(tmp_path):
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    return tmp_path / "provenance.ttl"


def claim(tmp_path, cid, agent, state):
    return run(["claim", "--id", cid, "--text", "x", "--parent", "draft-1", "--agent", agent, "--state", state], tmp_path)


def test_claim_refuses_human_only_states_for_an_ai_agent(tmp_path):
    ttl = graph(tmp_path)
    before = ttl.read_bytes()
    for state in ("human-read", "human-confirmed", "lit-read"):
        r = claim(tmp_path, "c-" + state, "model-x", state)
        assert r.returncode != 0 and "human-only" in (r.stdout + r.stderr), (state, r.stdout, r.stderr)
    assert ttl.read_bytes() == before


def test_claim_accepts_human_only_state_for_a_registered_human(tmp_path):
    graph(tmp_path)
    assert run(["agent", "--id", "person-y", "--type", "human", "--name", "P"], tmp_path).returncode == 0
    r = claim(tmp_path, "c-human", "person-y", "human-read")
    assert r.returncode == 0, r.stdout + r.stderr


def test_claim_still_accepts_ai_confirmed_for_an_ai_agent(tmp_path):
    graph(tmp_path)
    r = claim(tmp_path, "c-ai", "model-x", "ai-confirmed")
    assert r.returncode == 0, r.stdout + r.stderr


def test_source_refuses_human_only_states_without_a_human(tmp_path):
    ttl = graph(tmp_path)
    before = ttl.read_bytes()
    r = run(["source", "--id", "s-ai", "--url", "https://example.org/a", "--state", "human-confirmed",
             "--agent", "model-x"], tmp_path)
    assert r.returncode != 0 and "human-only" in (r.stdout + r.stderr)
    r = run(["source", "--id", "s-none", "--url", "https://example.org/a", "--state", "human-read"], tmp_path)
    assert r.returncode != 0 and "no --agent" in (r.stdout + r.stderr)
    assert ttl.read_bytes() == before


def test_source_accepts_human_only_state_for_a_registered_human(tmp_path):
    graph(tmp_path)
    run(["agent", "--id", "person-y", "--type", "human", "--name", "P"], tmp_path)
    r = run(["source", "--id", "s-human", "--url", "https://example.org/a", "--state", "human-read",
             "--agent", "person-y"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_promote_names_a_state_off_the_ladder_without_a_traceback(tmp_path):
    graph(tmp_path)
    run(["agent", "--id", "person-y", "--type", "human", "--name", "P"], tmp_path)
    assert claim(tmp_path, "c-contested", "model-x", "contested").returncode == 0
    r = run(["promote", "--id", "c-contested", "--to", "human-read", "--agent", "person-y"], tmp_path)
    assert r.returncode != 0 and "not on the ladder" in (r.stdout + r.stderr)
    assert "Traceback" not in r.stderr


def test_claim_state_must_be_one_token_and_is_lowercased(tmp_path):
    ttl = graph(tmp_path)
    before = ttl.read_bytes()
    for state in ("x/human-read", "human read", "human-read\n"):
        r = claim(tmp_path, "c-bad", "model-x", state)
        assert r.returncode != 0 and "invalid state" in (r.stdout + r.stderr), (state, r.stdout, r.stderr)
    assert ttl.read_bytes() == before
    r = claim(tmp_path, "c-case", "model-x", "Human-Read")
    assert r.returncode != 0 and "human-only" in (r.stdout + r.stderr)
    assert claim(tmp_path, "c-upper", "model-x", "Ai-Confirmed").returncode == 0
    g = Graph()
    g.parse(ttl, format="turtle")
    claim_iri = URIRef(BASE + "claim/c-upper")
    states = set(g.objects(claim_iri, URIRef("https://w3id.org/aiprov/ns#verificationState")))
    assert states == {URIRef(BASE + "verification/ai-confirmed")}


def test_source_refuses_the_legacy_alias_for_an_ai_agent(tmp_path):
    graph(tmp_path)
    r = run(["source", "--id", "s-alias", "--url", "https://example.org/a", "--state", "lit-read",
             "--agent", "model-x"], tmp_path)
    assert r.returncode != 0 and "human-only" in (r.stdout + r.stderr)
