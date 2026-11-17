"""Canonical rung IRIs, opt-in (issue 11)."""
import os, pathlib, shutil, subprocess, sys
from rdflib import Graph, Namespace, URIRef

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "versions"
BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "PROV_ACTOR": ""}, check=False)


def load(d):
    g = Graph(); g.parse(d / "provenance.ttl", format="turtle"); return g


def seed(d, *init_args):
    assert run(["init", *init_args], d).returncode == 0
    assert run(["agent", "--id", "ai1", "--type", "ai", "--model", "m", "--provider", "p"], d).returncode == 0
    assert run(["log", "--activity", "a1", "--agent", "ai1"], d).returncode == 0


def state(d, cid):
    return str(load(d).value(URIRef(f"{BASE}claim/{cid}"), AIPROV.verificationState))


def test_default_stays_project_namespace(tmp_path):
    seed(tmp_path)
    assert run(["claim", "--id", "c1", "--text", "t", "--parent", "a1", "--agent", "ai1", "--state", "unverified"], tmp_path).returncode == 0
    assert state(tmp_path, "c1") == BASE + "verification/unverified"


def test_canonical_flag_new_records_use_the_vocabulary_iri(tmp_path):
    seed(tmp_path, "--canonical-rungs")
    r = run(["claim", "--id", "c1", "--text", "t", "--parent", "a1", "--agent", "ai1", "--state", "unverified"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert state(tmp_path, "c1") == str(AIPROV["rung-unverified"])
    r = run(["promote", "--id", "c1", "--to", "ai-confirmed", "--agent", "ai1"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert state(tmp_path, "c1") == str(AIPROV["rung-ai-confirmed"])
    assert run(["validate"], tmp_path).returncode == 0
    rep = run(["report"], tmp_path)
    assert rep.returncode == 0 and "ai-confirmed" in rep.stdout


def test_both_forms_are_one_rung(tmp_path):
    seed(tmp_path)
    run(["claim", "--id", "old", "--text", "t", "--parent", "a1", "--agent", "ai1", "--state", "unverified"], tmp_path)
    assert run(["migrate", "--canonical-rungs"], tmp_path).returncode == 0
    run(["claim", "--id", "new", "--text", "t", "--parent", "a1", "--agent", "ai1", "--state", "unverified"], tmp_path)
    assert state(tmp_path, "old") == BASE + "verification/unverified"
    assert state(tmp_path, "new") == str(AIPROV["rung-unverified"])
    assert run(["promote", "--id", "old", "--to", "ai-confirmed", "--agent", "ai1"], tmp_path).returncode == 0
    assert run(["validate"], tmp_path).returncode == 0
    g = load(tmp_path)
    same = URIRef("http://www.w3.org/2002/07/owl#sameAs")
    a, b = URIRef(BASE + "verification/human-verified"), AIPROV["rung-human-verified"]
    assert (a, same, b) in g or (b, same, a) in g


def test_human_only_rung_still_refused_for_ai_in_canonical_graph(tmp_path):
    seed(tmp_path, "--canonical-rungs")
    run(["claim", "--id", "c1", "--text", "t", "--parent", "a1", "--agent", "ai1", "--state", "unverified"], tmp_path)
    assert run(["promote", "--id", "c1", "--to", "human-read", "--agent", "ai1"], tmp_path).returncode != 0


def test_merge_of_a_canonical_shard_keeps_the_higher_rung(tmp_path):
    main = tmp_path / "main"; main.mkdir(); seed(main)
    run(["claim", "--id", "c1", "--text", "t", "--parent", "a1", "--agent", "ai1", "--state", "unverified"], main)
    shard = tmp_path / "shard"; shard.mkdir(); shutil.copy(main / "provenance.ttl", shard / "provenance.ttl")
    assert run(["migrate", "--canonical-rungs"], shard).returncode == 0
    run(["promote", "--id", "c1", "--to", "ai-confirmed", "--agent", "ai1"], shard)
    r = run(["merge", "--from", str(shard / "provenance.ttl")], main)
    assert r.returncode == 0, r.stdout + r.stderr
    assert run(["validate"], main).returncode == 0
