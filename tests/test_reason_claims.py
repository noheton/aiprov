"""Reason of an activity as a claim with a reason source (issue 51)."""
import subprocess, sys

BASE = "https://example.org/prov/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def setup(p):
    for a in (["init"], ["agent", "--id", "m1", "--type", "ai", "--model", "m-1"],
              ["log", "--activity", "act", "--pass", "authoring", "--agent", "m1"]):
        assert run(a, p).returncode == 0


def reason(p, cid, *extra):
    return run(["claim", "--id", cid, "--text", "why", "--parent", "act", "--agent", "m1", *extra], p)


def test_reasons_validate(tmp_path):
    setup(tmp_path)
    assert reason(tmp_path, "r1", "--reason-source", "agent-stated").returncode == 0
    assert reason(tmp_path, "r2", "--reason-source", "owner-stated", "--reason-ref", "issue-48").returncode == 0
    assert run(["validate"], tmp_path).returncode == 0
    ttl = (tmp_path / "provenance.ttl").read_text()
    assert "reasonSource" in ttl and "wasInfluencedBy" in ttl


def test_owner_stated_by_ai_needs_ref(tmp_path):
    setup(tmp_path)
    assert reason(tmp_path, "r1", "--reason-source", "owner-stated").returncode != 0


def test_invalid_source_rejected(tmp_path):
    setup(tmp_path)
    assert reason(tmp_path, "r1", "--reason-source", "guess").returncode != 0


def test_influencing_claim_without_source_fails(tmp_path):
    setup(tmp_path)
    assert reason(tmp_path, "r1").returncode == 0
    g = tmp_path / "provenance.ttl"
    g.write_text(g.read_text() + f"\n<{BASE}activity/act> <http://www.w3.org/ns/prov#wasInfluencedBy> <{BASE}claim/r1> .\n")
    assert run(["validate"], tmp_path).returncode != 0
