"""provlog migrate: every earlier release's fixture migrates, validates, and a second run changes nothing (issue 42)."""
import pathlib, shutil, subprocess, sys
from rdflib import Graph, Namespace, RDF

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = sorted((ROOT / "tests" / "fixtures" / "versions").glob("v*.ttl"))
BASE = "https://example.org/prov/"
AIPROV = Namespace("https://w3id.org/aiprov/ns#")


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def setup(tmp_path, fixture):
    shutil.copy(fixture, tmp_path / "provenance.ttl")


def test_fixtures_exist_for_every_earlier_release():
    assert {f.stem for f in FIXTURES} >= {"v0.1.0", "v0.2.0"}


def test_every_fixture_migrates_and_validates(tmp_path):
    for fx in FIXTURES:
        d = tmp_path / fx.stem; d.mkdir(); setup(d, fx)
        before = Graph(); before.parse(d / "provenance.ttl", format="turtle")
        r = run(["migrate"], d)
        assert r.returncode == 0, fx.name + r.stdout + r.stderr
        after = Graph(); after.parse(d / "provenance.ttl", format="turtle")
        assert all(t in after for t in before), "migrate dropped a triple of " + fx.name
        assert {str(o) for o in after.objects(None, AIPROV.schemaVersion)} == {"0.3.0"}
        assert len(list(after.subjects(RDF.type, AIPROV.Migration))) == 1
        v = run(["validate"], d)
        assert v.returncode == 0, v.stdout + v.stderr
        assert "WARN] graph states its schema version" not in v.stdout


def test_second_run_is_a_no_op(tmp_path):
    setup(tmp_path, FIXTURES[0])
    assert run(["migrate"], tmp_path).returncode == 0
    snap = (tmp_path / "provenance.ttl").read_bytes()
    r = run(["migrate"], tmp_path)
    assert r.returncode == 0 and "nothing to migrate" in r.stdout
    assert (tmp_path / "provenance.ttl").read_bytes() == snap


def test_dry_run_writes_nothing_and_reports(tmp_path):
    setup(tmp_path, FIXTURES[0])
    snap = (tmp_path / "provenance.ttl").read_bytes()
    r = run(["migrate", "--dry-run"], tmp_path)
    assert r.returncode == 0 and "dry run" in r.stdout and "0.1.0 -> 0.3.0" in r.stdout
    assert (tmp_path / "provenance.ttl").read_bytes() == snap


def test_unknown_terms_survive_and_downgrade_is_refused(tmp_path):
    setup(tmp_path, FIXTURES[0])
    with open(tmp_path / "provenance.ttl", "a", encoding="utf-8") as f:
        f.write('\n<https://example.org/prov/entity/x> <https://example.org/own#flag> "keep" .\n')
    assert run(["migrate"], tmp_path).returncode == 0
    assert "keep" in (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    r = run(["migrate", "--to", "0.1.0"], tmp_path)
    assert r.returncode != 0 and "not supported" in (r.stdout + r.stderr)


def test_init_stamps_the_version_and_validate_warns_without_it(tmp_path):
    assert run(["init"], tmp_path).returncode == 0
    assert "WARN] graph states" not in run(["validate"], tmp_path).stdout
    setup(tmp_path, FIXTURES[0])
    v = run(["validate"], tmp_path)
    assert v.returncode == 0 and "WARN] graph states its schema version" in v.stdout


def test_dashboard_reads_every_version_without_changing_the_file(tmp_path):
    from aiprov import build_dashboard as bd
    for fx in FIXTURES:
        d = tmp_path / fx.stem; d.mkdir(); setup(d, fx)
        snap = (d / "provenance.ttl").read_bytes()
        data = bd.extract(d / "provenance.ttl")
        assert data["claims"] and data["activities"] and data["agents"]
        assert (d / "provenance.ttl").read_bytes() == snap
        assert run(["validate"], d).returncode == 0
