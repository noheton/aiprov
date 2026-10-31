"""Sessions: type, start, end and outcome on a Session node; activities are part of it (issue 8)."""
import pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BAD = ROOT / "tests" / "fixtures" / "session-bad.ttl"
BASE = "https://example.org/prov/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def ok(args, cwd):
    r = run(args, cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def setup(tmp_path):
    ok(["init"], tmp_path)
    ok(["agent", "--id", "m1", "--type", "ai", "--model", "m"], tmp_path)


def two_sessions(tmp_path):
    setup(tmp_path)
    ok(["log", "--activity", "a1", "--agent", "m1", "--session", "s-chat", "--session-type", "interactive-chat",
        "--session-started", "2026-10-30T09:00:00+00:00"], tmp_path)
    ok(["log", "--activity", "a2", "--agent", "m1", "--session", "s-chat", "--session-outcome", "succeeded",
        "--session-ended", "2026-10-30T10:00:00+00:00"], tmp_path)
    ok(["log", "--activity", "b1", "--agent", "m1", "--session", "s-batch", "--session-type", "batch",
        "--session-outcome", "failed"], tmp_path)


def test_two_sessions_validate_and_report_groups_by_type(tmp_path):
    two_sessions(tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    rep = ok(["report"], tmp_path).stdout
    assert "activities:         3" in rep
    assert "interactive-chat" in rep and "1 sessions, 2 activities, succeeded 1" in rep
    assert "batch" in rep and "1 sessions, 1 activities, failed 1" in rep
    ttl = (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    assert "isPartOf" in ttl and "sessionType-batch" in ttl


def test_session_values_are_write_once(tmp_path):
    two_sessions(tmp_path)
    before = (tmp_path / "provenance.ttl").read_bytes()
    for args in (["--session-type", "evaluation"], ["--session-outcome", "interrupted"],
                 ["--session-ended", "2026-10-30T11:00:00+00:00"]):
        r = run(["log", "--activity", "a3", "--agent", "m1", "--session", "s-chat", *args], tmp_path)
        assert r.returncode != 0 and "append-only" in (r.stdout + r.stderr), args
    assert (tmp_path / "provenance.ttl").read_bytes() == before
    ok(["log", "--activity", "a3", "--agent", "m1", "--session", "s-chat", "--session-type", "interactive-chat"], tmp_path)


def test_session_options_need_a_session_and_valid_values(tmp_path):
    setup(tmp_path)
    r = run(["log", "--activity", "x", "--session-type", "batch"], tmp_path)
    assert r.returncode != 0 and "need --session" in (r.stdout + r.stderr)
    r = run(["log", "--activity", "x", "--session", "s", "--session-type", "lunch"], tmp_path)
    assert r.returncode != 0 and "not one of" in (r.stdout + r.stderr)
    r = run(["log", "--activity", "x", "--session", "s", "--session-started", "yesterday"], tmp_path)
    assert r.returncode != 0 and "ISO 8601" in (r.stdout + r.stderr)
    r = run(["log", "--activity", "x", "--session", "s", "--session-started", "2026-10-30T10:00:00+00:00",
             "--session-ended", "2026-10-30T09:00:00+00:00"], tmp_path)
    assert r.returncode != 0 and "before it started" in (r.stdout + r.stderr)


def test_adopter_type_by_iri(tmp_path):
    setup(tmp_path)
    ok(["log", "--activity", "x", "--agent", "m1", "--session", "s",
        "--session-type", "https://example.org/types#review"], tmp_path)
    assert "types#review" in (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    assert ok(["validate"], tmp_path).returncode == 0


def test_validator_fails_on_a_part_of_a_missing_session(tmp_path):
    shutil.copy(BAD, tmp_path / "provenance.ttl")
    r = run(["validate"], tmp_path)
    assert r.returncode == 1
    assert "[FAIL] activities that are part of something that is not a session: 1" in r.stdout


def test_legacy_graph_without_sessions_is_unchanged(tmp_path):
    setup(tmp_path)
    ok(["log", "--activity", "plain", "--agent", "m1"], tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    assert "-- sessions --" not in ok(["report"], tmp_path).stdout
