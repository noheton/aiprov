"""Smoke tests: the shipped schema parses; a real graph validates; human-only rungs are refused."""
import pathlib, subprocess, sys, shutil
from rdflib import Graph, URIRef

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

def test_log_records_when_it_was_written_apart_from_the_work(tmp_path):
    """The span of the work and the moment of bookkeeping are different facts, so they are different fields."""
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    r = run(["--base", "https://example.org/prov/", "log", "--activity", "span-demo", "--pass", "build",
             "--agent", "model-x", "--started", "2026-01-01T09:00:00+00:00",
             "--ended", "2026-01-01T17:30:00+00:00", "--session-id", "ses-1",
             "--label", "work that took a day and was written down afterwards"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    g = Graph(); g.parse(tmp_path / "provenance.ttl", format="turtle")
    act = next(s for s in g.subjects() if str(s).endswith("/activity/span-demo"))
    started = g.value(act, URIRef("http://www.w3.org/ns/prov#startedAtTime"))
    ended = g.value(act, URIRef("http://www.w3.org/ns/prov#endedAtTime"))
    recorded = g.value(act, URIRef("https://w3id.org/aiprov/ns#recordedAtTime"))
    assert started is not None and ended is not None and recorded is not None
    # --ended is honoured rather than silently replaced by the clock, so the span is the work.
    assert (ended.toPython() - started.toPython()).total_seconds() == 8.5 * 3600
    # ...and the record still says when it was written, which is later than the work it describes.
    assert recorded.toPython() > ended.toPython()


def test_validate_flags_a_session_activity_that_is_only_an_instant(tmp_path):
    """A sub-second span on a session activity is the moment of logging; validate says so instead of implying a span."""
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    r = run(["--base", "https://example.org/prov/", "log", "--activity", "instant-demo", "--pass", "build",
             "--agent", "model-x", "--session-id", "ses-1", "--label", "logged in arrears"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    v = run(["--base", "https://example.org/prov/", "validate"], tmp_path)
    assert v.returncode == 0, v.stdout + v.stderr          # a WARN, never a failure
    line = [x for x in v.stdout.splitlines() if "logging instant" in x]
    assert line and line[0].startswith("[WARN]"), v.stdout
