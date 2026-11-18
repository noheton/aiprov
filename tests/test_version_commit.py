"""provlog --version, validate header, and the version recorded on promotions (issue 25)."""
import subprocess, sys
from rdflib import Graph, Namespace

BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")


def run(cwd, *args):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def test_version_prints_version_and_commit_or_unknown(tmp_path):
    r = run(tmp_path, "--version")
    assert r.returncode == 0
    assert r.stdout.startswith("provlog version ") and " commit " in r.stdout


def test_validate_header_is_one_parsable_line(tmp_path):
    run(tmp_path, "init")
    r = run(tmp_path, "validate")
    assert r.stdout.splitlines()[0].startswith("provlog version ")


def test_promote_records_validator_version(tmp_path):
    run(tmp_path, "init")
    run(tmp_path, "agent", "--id", "h", "--type", "human", "--name", "H")
    run(tmp_path, "agent", "--id", "m", "--type", "ai", "--model", "x", "--provider", "y", "--acted-on-behalf-of", "h")
    run(tmp_path, "log", "--activity", "a1", "--pass", "authoring", "--agent", "m", "--label", "x")
    run(tmp_path, "claim", "--id", "c1", "--text", "t", "--parent", "a1", "--agent", "m", "--state", "unverified")
    r = run(tmp_path, "promote", "--id", "c1", "--to", "ai-confirmed", "--agent", "m")
    assert r.returncode == 0, r.stderr
    g = Graph().parse(tmp_path / "provenance.ttl")
    assert list(g.objects(None, AIPROV.validatorVersion))
    assert list(g.objects(None, AIPROV.validatorCommit))
