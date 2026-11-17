"""Reason of an activity as a claim with a reason source (issue 51)."""
import os, pathlib, subprocess, sys

from rdflib import Graph, Namespace, URIRef

BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")
PROV = Namespace("http://www.w3.org/ns/prov#")


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "PROV_ACTOR": ""})


def seed(d):
    assert run(["init"], d).returncode == 0
    assert run(["agent", "--id", "ai1", "--type", "ai", "--model", "m", "--provider", "p"], d).returncode == 0
    assert run(["log", "--activity", "a1", "--agent", "ai1"], d).returncode == 0


CLAIM = ["claim", "--id", "r1", "--text", "Chose A: see issue 7", "--parent", "a1", "--agent", "ai1"]


def test_reason_claim_links_the_activity_and_keeps_its_source(tmp_path):
    seed(tmp_path)
    r = run(CLAIM + ["--reason-for", "a1", "--reason-source", "agent-stated"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    g = Graph(); g.parse(tmp_path / "provenance.ttl", format="turtle")
    c = URIRef(BASE + "claim/r1")
    assert (URIRef(BASE + "activity/a1"), PROV.wasInfluencedBy, c) in g
    assert str(g.value(c, AIPROV.reasonSource)) == "agent-stated"
    assert str(g.value(c, AIPROV.verificationState)).endswith("/unverified")
    assert run(["validate"], tmp_path).returncode == 0


def test_flags_go_together_and_values_are_checked(tmp_path):
    seed(tmp_path)
    assert run(CLAIM + ["--reason-for", "a1"], tmp_path).returncode != 0
    assert run(CLAIM + ["--reason-source", "derived"], tmp_path).returncode != 0
    assert run(CLAIM + ["--reason-for", "a1", "--reason-source", "guess"], tmp_path).returncode != 0
    assert run(CLAIM + ["--reason-for", "nope", "--reason-source", "derived"], tmp_path).returncode != 0
    assert "r1" not in (tmp_path / "provenance.ttl").read_text(encoding="utf-8")


def test_validate_fails_a_reason_claim_without_a_source(tmp_path):
    seed(tmp_path)
    assert run(CLAIM, tmp_path).returncode == 0
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f"\n<{BASE}activity/a1> <http://www.w3.org/ns/prov#wasInfluencedBy> <{BASE}claim/r1> .\n")
    v = run(["validate"], tmp_path)
    assert v.returncode != 0 and "reason claims without a valid reasonSource: 1" in v.stdout
