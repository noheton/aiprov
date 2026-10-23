"""Multi-agent runs: plan before launch, delegation links, validator rules."""
import pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BAD = ROOT / "tests" / "fixtures" / "orchestration-bad.ttl"
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
    ok(["agent", "--id", "orch", "--type", "ai", "--model", "m-orch"], tmp_path)
    for w in ("rev1", "rev2", "stray"):
        ok(["agent", "--id", w, "--type", "ai", "--model", "m-sub", "--acted-on-behalf-of", "orch"], tmp_path)


def plan(tmp_path):
    ok(["log", "--activity", "o1", "--orchestration", "--agent", "orch",
        "--planned-agent", "rev1", "--planned-agent", "rev2",
        "--planned-role", "correctness", "--planned-role", "security"], tmp_path)


def test_planned_run_validates_and_reports(tmp_path):
    setup(tmp_path); plan(tmp_path)
    ok(["log", "--activity", "o1-a", "--informed-by", "o1", "--agent", "rev1", "--role", "correctness",
        "--total-tokens", "100"], tmp_path)
    ok(["log", "--activity", "o1-b", "--informed-by", "o1", "--agent", "rev2", "--role", "security"], tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    rep = ok(["report"], tmp_path).stdout
    assert "-- orchestration --" in rep and "2 sub-activities" in rep and "100 tokens reported by 1" in rep
    ttl = (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    assert "actedOnBehalfOf" in ttl and "wasInformedBy" in ttl


def test_planned_agent_must_be_registered_first(tmp_path):
    ok(["init"], tmp_path)
    r = run(["log", "--activity", "o1", "--orchestration", "--planned-agent", "ghost"], tmp_path)
    assert r.returncode != 0 and "not registered" in (r.stdout + r.stderr)


def test_log_refuses_what_the_plan_does_not_allow(tmp_path):
    setup(tmp_path); plan(tmp_path)
    for args, msg in (
        (["--agent", "stray", "--role", "correctness"], "not among the planned agents"),
        (["--agent", "rev1", "--role", "lunch"], "not among the planned roles"),
    ):
        r = run(["log", "--activity", "x", "--informed-by", "o1", *args], tmp_path)
        assert r.returncode != 0 and msg in (r.stdout + r.stderr)
    r = run(["log", "--activity", "y", "--informed-by", "nope", "--agent", "rev1"], tmp_path)
    assert r.returncode != 0 and "is not logged" in (r.stdout + r.stderr)
    r = run(["log", "--activity", "z", "--planned-role", "a"], tmp_path)
    assert r.returncode != 0 and "need --orchestration" in (r.stdout + r.stderr)


def test_validator_catches_a_hand_edited_graph(tmp_path):
    shutil.copy(BAD, tmp_path / "provenance.ttl")
    r = run(["validate"], tmp_path)
    out = r.stdout
    assert r.returncode == 1
    assert "[FAIL] wasInformedBy targets that are not logged activities: 1" in out
    assert "[FAIL] sub-activities outside the orchestration plan: 3" in out  # wrong role, no agent, no role
    assert "[FAIL] orchestrations logged twice or informed by themselves: 1" in out
    assert "[FAIL] sub-activities logged before their orchestration: 1" in out


def test_omitting_agent_or_role_does_not_bypass_the_plan(tmp_path):
    setup(tmp_path); plan(tmp_path)
    r = run(["log", "--activity", "bare", "--informed-by", "o1"], tmp_path)
    assert r.returncode != 0 and "--agent is required" in (r.stdout + r.stderr)
    r = run(["log", "--activity", "bare", "--informed-by", "o1", "--agent", "rev1"], tmp_path)
    assert r.returncode != 0 and "--role is required" in (r.stdout + r.stderr)


def test_orchestrations_cannot_be_relogged_or_loop(tmp_path):
    setup(tmp_path); plan(tmp_path)
    r = run(["log", "--activity", "o1", "--orchestration", "--planned-agent", "stray"], tmp_path)
    assert r.returncode != 0 and "already logged" in (r.stdout + r.stderr)
    r = run(["log", "--activity", "o1"], tmp_path)
    assert r.returncode != 0 and "already logged" in (r.stdout + r.stderr)
    r = run(["log", "--activity", "o1", "--informed-by", "o1"], tmp_path)
    assert r.returncode != 0 and "cannot be informed by itself" in (r.stdout + r.stderr)
