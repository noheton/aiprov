"""Smoke tests: the shipped schema parses; a real graph validates; human-only rungs are refused."""
import pathlib, subprocess, sys, shutil
from rdflib import Graph

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "example-graph.ttl"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", *args], cwd=cwd,
                          capture_output=True, text=True)


def test_schema_parses():
    g = Graph(); g.parse(ROOT / "schema" / "aiprov-schema.ttl", format="turtle")
    assert len(g) > 100


def test_fixture_validates(tmp_path):
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    r = run(["--base", "https://example.org/prov/", "validate"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ai_cannot_grant_human_rung(tmp_path):
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    r = run(["--base", "https://example.org/prov/", "promote",
             "--id", "src1", "--to", "human-read", "--agent", "model-x"], tmp_path)
    assert r.returncode != 0 and "human-only" in (r.stdout + r.stderr)


def test_init_seeds(tmp_path):
    r = run(["--base", "https://example.org/x/", "init"], tmp_path)
    assert r.returncode == 0 and (tmp_path / "provenance.ttl").exists()
