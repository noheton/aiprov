"""Capture path of a record: who wrote it, from what, auxiliary passes, one telemetry witness per session (issue 24)."""
import pathlib, subprocess, sys

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
    ok(["agent", "--id", "rec", "--type", "ai", "--model", "m2"], tmp_path)


def test_self_report_backfill_and_auxiliary_validate_and_report(tmp_path):
    setup(tmp_path)
    summary = tmp_path / "summary.md"
    summary.write_text("compaction summary", encoding="utf-8")
    ok(["log", "--activity", "a1", "--agent", "m1", "--session", "s1", "--capture-path", "self-report",
        "--input-tokens", "100", "--output-tokens", "20"], tmp_path)
    ok(["log", "--activity", "a2", "--agent", "m1", "--session", "s2", "--capture-path", "backfill",
        "--recorded-by", "rec", "--recorded-from", str(summary)], tmp_path)
    ok(["log", "--activity", "x1", "--agent", "m1", "--session", "s1", "--pass", "auxiliary",
        "--capture-path", "harness-export", "--input-tokens", "5000", "--output-tokens", "3591"], tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    rep = ok(["report"], tmp_path).stdout
    assert "total tokens:       120" in rep          # the auxiliary pass is not in the totals
    assert "auxiliary passes" in rep and "8591 tokens" in rep
    assert "backfill" in rep and "self-report" in rep


def test_backfill_without_source_warns(tmp_path):
    setup(tmp_path)
    ok(["log", "--activity", "a2", "--agent", "m1", "--capture-path", "backfill"], tmp_path)
    out = ok(["validate"], tmp_path).stdout
    assert "[WARN] records made by another agent or in arrears without a source (recordedFrom): 1" in out
    ok(["log", "--activity", "a3", "--agent", "m1", "--recorded-by", "rec"], tmp_path)
    assert "without a source (recordedFrom): 2" in ok(["validate"], tmp_path).stdout


def test_two_witnesses_for_one_session_are_not_summed(tmp_path):
    setup(tmp_path)
    ok(["log", "--activity", "g1", "--agent", "m1", "--session", "s1", "--capture-path", "gateway",
        "--total-tokens", "1000"], tmp_path)
    ok(["log", "--activity", "h1", "--agent", "m1", "--session", "s1", "--capture-path", "harness-export",
        "--total-tokens", "900"], tmp_path)
    assert "[WARN] sessions with token sums from more than one capture path (only one is counted): 1" \
        in ok(["validate"], tmp_path).stdout
    rep = ok(["report"], tmp_path).stdout
    assert "total tokens:       1000" in rep
    assert "not counted" in rep and "900 tokens" in rep


def test_unknown_path_and_unregistered_recorder_are_refused(tmp_path):
    setup(tmp_path)
    assert run(["log", "--activity", "a", "--capture-path", "magic"], tmp_path).returncode != 0
    before = (tmp_path / "provenance.ttl").read_bytes()
    assert run(["log", "--activity", "a", "--agent", "m1", "--recorded-by", "nobody"], tmp_path).returncode != 0
    assert (tmp_path / "provenance.ttl").read_bytes() == before


def test_activity_without_capture_path_is_unknown_not_defaulted(tmp_path):
    setup(tmp_path)
    ok(["log", "--activity", "a1", "--agent", "m1", "--total-tokens", "10"], tmp_path)
    from rdflib import Graph, Namespace
    g = Graph(); g.parse(tmp_path / "provenance.ttl", format="turtle")
    cp = Namespace("https://w3id.org/aiprov/ns#").capturePath
    assert not [s for s, _, _ in g.triples((None, cp, None)) if "activity" in str(s)]
    assert ok(["validate"], tmp_path).returncode == 0
