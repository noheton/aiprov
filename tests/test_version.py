"""provlog --version and validatorVersion on promotions (issue 25)."""
import json, os, pathlib, subprocess, sys

from rdflib import Graph, Namespace

from aiprov import provlog

BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "PROV_ACTOR": ""})


def test_version_flag_prints_the_version(tmp_path):
    r = run(["--version"], tmp_path)
    assert r.returncode == 0 and r.stdout.startswith("aiprov ")


def test_commit_is_read_from_direct_url_json():
    text = json.dumps({"url": "https://example.org/x", "vcs_info": {"vcs": "git", "commit_id": "0123456789abcdef"}})
    assert provlog._commit_from_direct_url(text) == "0123456789abcdef"
    assert provlog._commit_from_direct_url(None) is None
    assert provlog._commit_from_direct_url("{}") is None


def test_validate_header_and_promotion_carry_the_version(tmp_path):
    assert run(["init"], tmp_path).returncode == 0
    assert run(["agent", "--id", "ai1", "--type", "ai", "--model", "m", "--provider", "p"], tmp_path).returncode == 0
    assert run(["log", "--activity", "a1", "--agent", "ai1"], tmp_path).returncode == 0
    assert run(["claim", "--id", "c1", "--text", "t", "--parent", "a1", "--agent", "ai1", "--state", "unverified"], tmp_path).returncode == 0
    assert run(["promote", "--id", "c1", "--to", "ai-confirmed", "--agent", "ai1"], tmp_path).returncode == 0
    v = run(["validate"], tmp_path)
    assert v.returncode == 0 and v.stdout.splitlines()[0].startswith("aiprov ")
    g = Graph(); g.parse(tmp_path / "provenance.ttl", format="turtle")
    vals = [str(o) for o in g.objects(None, AIPROV.validatorVersion)]
    assert len(vals) == 1 and vals[0].startswith("aiprov ")
