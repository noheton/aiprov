"""Vendoring as a property, rung source-vendored deprecated (issue 10)."""
import os
import pathlib
import shutil
import subprocess
import sys

from rdflib import RDF, Graph, Namespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "versions"
BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")
VERIF = Namespace(BASE + "verification/")


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "PROV_ACTOR": ""}, check=False)


def load(d):
    g = Graph(); g.parse(d / "provenance.ttl", format="turtle")
    return g


def old_graph(tmp_path):
    shutil.copy(FIXTURES / "v0.2.0.ttl", tmp_path / "provenance.ttl")
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f"""
<{BASE}source/stored> a aiprov:Source ; aiprov:verificationState verif:source-vendored .
<{BASE}source/checked> a aiprov:Source ; aiprov:verificationState verif:source-vendored .
<{BASE}activity/promote-checked-ai-confirmed> a aiprov:AuditPass ;
    rdfs:label "Promotion of checked: reference-resolved -> ai-confirmed"@en ;
    <http://www.w3.org/ns/prov#used> <{BASE}source/checked> .
""")
    return tmp_path


def test_migration_never_raises_a_rung_and_marks_the_fallback(tmp_path):
    d = old_graph(tmp_path)
    r = run(["migrate"], d)
    assert r.returncode == 0, r.stdout + r.stderr
    g = load(d)
    stored, checked = (g.value(__import__("rdflib").URIRef(f"{BASE}source/{n}"), AIPROV.verificationState) for n in ("stored", "checked"))
    assert str(stored).endswith("/unverified")
    assert str(checked).endswith("/reference-resolved")
    assert len(list(g.subjects(AIPROV.rungFallback, None))) == 1
    assert (VERIF["source-vendored"], __import__("rdflib").OWL.deprecated, None) in g


def test_dry_run_leaves_the_file_alone(tmp_path):
    d = old_graph(tmp_path)
    snap = (d / "provenance.ttl").read_bytes()
    assert run(["migrate", "--dry-run"], d).returncode == 0
    assert (d / "provenance.ttl").read_bytes() == snap


def test_source_vendor_records_hash_and_keeps_the_rung(tmp_path):
    shutil.copy(FIXTURES / "v0.2.0.ttl", tmp_path / "provenance.ttl")
    assert run(["migrate"], tmp_path).returncode == 0
    f = tmp_path / "paper.txt"; f.write_text("bytes")
    r = run(["source", "--id", "s1", "--url", "https://example.org/x", "--vendor", str(f)], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    g = load(tmp_path)
    ents = list(g.objects(None, AIPROV.vendoredFile))
    assert len(ents) == 1 and list(g.objects(ents[0], AIPROV.contentHash))
    assert str(next(g.objects(next(g.subjects(AIPROV.vendoredFile, None)), AIPROV.verificationState))).endswith("/unverified")
    assert run(["validate"], tmp_path).returncode == 0


def test_the_deprecated_rung_is_refused_and_validate_warns(tmp_path):
    d = old_graph(tmp_path)
    v = run(["validate"], d)
    assert "deprecated rung source-vendored" in v.stdout and "[WARN]" in v.stdout
    assert run(["source", "--id", "n", "--url", "https://example.org/y", "--state", "source-vendored"], d).returncode != 0


def test_vendored_file_without_hash_fails(tmp_path):
    shutil.copy(FIXTURES / "v0.2.0.ttl", tmp_path / "provenance.ttl")
    run(["migrate"], tmp_path)
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write(f"\n<{BASE}source/b> a aiprov:Source ; aiprov:vendoredFile <{BASE}entity/nofile> .\n<{BASE}entity/nofile> a aiprov:Artefact .\n")
    assert run(["validate"], tmp_path).returncode != 0
