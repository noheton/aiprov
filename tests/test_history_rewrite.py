"""History rewrite and repository import (issue 58)."""
import os, pathlib, subprocess, sys
from rdflib import Graph, Namespace, URIRef

BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")
OLD = ["a" * 40, "b" * 40, "c" * 40]
NEW = ["1" * 40, "2" * 40, "3" * 40]


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "PROV_ACTOR": ""}, check=False)


def setup(tmp_path):
    assert run(["init"], tmp_path).returncode == 0
    assert run(["agent", "--id", "h", "--type", "human", "--name", "H"], tmp_path).returncode == 0
    for i, c in enumerate(OLD):
        r = run(["log", "--activity", f"w{i}", "--pass", "authoring", "--agent", "h", "--commit", c,
                 "--label", "x", "--generated", f"f{i}.txt"], tmp_path)
        assert r.returncode == 0, r.stderr
    (tmp_path.parent / (tmp_path.name + "-map")).write_text(
        "old new\n" + "".join(f"{o} {n}\n" for o, n in zip(OLD, NEW)))
    return tmp_path.parent / (tmp_path.name + "-map")


def test_rewrite_links_every_referenced_commit_and_validates(tmp_path):
    m = setup(tmp_path)
    r = run(["rewrite", "--id", "rw1", "--agent", "h", "--map", str(m), "--old-head", OLD[2],
             "--new-head", NEW[2], "--tool", "git-filter-repo", "--removed-pattern", "data/"], tmp_path)
    assert r.returncode == 0, r.stderr
    g = Graph(); g.parse(tmp_path / "provenance.ttl", format="turtle")
    for o, n in zip(OLD, NEW):
        assert (URIRef(f"{BASE}commit/{o}"), AIPROV.rewrittenAs, URIRef(f"{BASE}commit/{n}")) in g
    assert str(m) not in (tmp_path / "provenance.ttl").read_text()  # the map path never enters the graph
    assert run(["validate"], tmp_path).returncode == 0


def test_validate_fails_on_unhashed_map(tmp_path):
    setup(tmp_path)
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f"<{BASE}activity/bad> a aiprov:HistoryRewrite .\n")
    assert run(["validate"], tmp_path).returncode == 1


def test_import_derives_root_from_source(tmp_path):
    setup(tmp_path)
    r = run(["import", "--id", "imp1", "--agent", "h", "--root-commit", NEW[0], "--source-commit", OLD[2]], tmp_path)
    assert r.returncode == 0, r.stderr
    g = Graph(); g.parse(tmp_path / "provenance.ttl", format="turtle")
    prov = Namespace("http://www.w3.org/ns/prov#")
    assert (URIRef(f"{BASE}commit/{NEW[0]}"), prov.wasDerivedFrom, URIRef(f"{BASE}commit/{OLD[2]}")) in g
    assert run(["validate"], tmp_path).returncode == 0
