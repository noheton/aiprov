"""Decision records: question, options, recommendation, who chose what, hash by default (issue 44)."""
import hashlib, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BAD = ROOT / "tests" / "fixtures" / "decision-bad.ttl"
BASE = "https://example.org/prov/"
OPTS = ["--option", "a=Build it as specified", "--option", "b=Leave it out"]


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def ok(args, cwd):
    r = run(args, cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def setup(tmp_path):
    ok(["init"], tmp_path)
    ok(["agent", "--id", "planner", "--type", "ai", "--model", "m-1"], tmp_path)
    ok(["agent", "--id", "alex", "--type", "human", "--name", "Alex Example"], tmp_path)


def opened(tmp_path, **kw):
    setup(tmp_path)
    ok(["decision", "open", "--id", "d1", "--agent", "planner", "--question", "Build feature X?", *OPTS,
        "--recommend", "a", "--asked-in", "https://example.org/tracker/issues/7"], tmp_path)


def test_flow_validates_and_hash_is_the_default(tmp_path):
    opened(tmp_path)
    ok(["decision", "decide", "--id", "d1", "--agent", "alex", "--choose", "a", "--state", "done",
        "--decided-in", "https://example.org/tracker/issues/7#c1"], tmp_path)
    ok(["log", "--activity", "build-x", "--agent", "planner", "--used-decision", "d1"], tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    ttl = (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    assert "Build feature X?" not in ttl and "Leave it out" not in ttl
    assert hashlib.sha256(b"Build feature X?").hexdigest() in ttl
    assert "open 0, provisional 0, done 1, superseded 0" in ok(["report"], tmp_path).stdout


def test_keep_text_only_in_a_class_that_allows_it(tmp_path):
    setup(tmp_path)
    base = ["decision", "open", "--id", "d2", "--agent", "planner", "--question", "Q?", *OPTS, "--keep-text"]
    assert run(base, tmp_path).returncode != 0                                   # no data class given
    assert run([*base, "--data-class", "confidential"], tmp_path).returncode != 0
    ok([*base, "--data-class", "internal"], tmp_path)
    assert "Leave it out" in (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    assert ok(["validate"], tmp_path).returncode == 0


def test_an_ai_cannot_close_a_decision_but_may_set_provisional(tmp_path):
    opened(tmp_path)
    before = (tmp_path / "provenance.ttl").read_bytes()
    r = run(["decision", "decide", "--id", "d1", "--agent", "planner", "--choose", "a", "--state", "done"], tmp_path)
    assert r.returncode != 0 and "human-only" in r.stdout + r.stderr
    assert (tmp_path / "provenance.ttl").read_bytes() == before
    ok(["decision", "decide", "--id", "d1", "--agent", "planner", "--choose", "a", "--state", "provisional"], tmp_path)
    assert "open 0, provisional 1, done 0" in ok(["report"], tmp_path).stdout
    ok(["decision", "decide", "--id", "d1", "--agent", "alex", "--choose", "b", "--state", "done"], tmp_path)
    assert "done 1" in ok(["report"], tmp_path).stdout


def test_refusals_leave_the_file_unchanged(tmp_path):
    opened(tmp_path)
    before = (tmp_path / "provenance.ttl").read_bytes()
    cases = [["open", "--id", "d1", "--agent", "planner", "--question", "Q", *OPTS],              # append-only
             ["open", "--id", "x1", "--agent", "ghost", "--question", "Q", *OPTS],                # unregistered
             ["open", "--id", "x2", "--agent", "planner", "--question", "Q", "--option", "a=only"],  # one option
             ["open", "--id", "x3", "--agent", "planner", "--question", "Q", *OPTS, "--recommend", "z"],
             ["open", "--id", "x4", "--agent", "planner", "--question", "Q", "--option", "a=1", "--option", "a=2"],
             ["decide", "--id", "nope", "--agent", "alex", "--choose", "a"],
             ["decide", "--id", "d1", "--agent", "alex", "--choose", "zz"],                       # not offered
             ["supersede", "--id", "d1", "--old", "d1"],
             ["supersede", "--id", "d1", "--old", "missing"]]
    for args in cases:
        r = run(["decision", *args], tmp_path)
        assert r.returncode != 0 and "Traceback" not in r.stdout + r.stderr, (args, r.stdout, r.stderr)
    assert (tmp_path / "provenance.ttl").read_bytes() == before


def test_a_done_decision_is_not_edited_but_superseded(tmp_path):
    opened(tmp_path)
    ok(["decision", "decide", "--id", "d1", "--agent", "alex", "--choose", "a"], tmp_path)
    assert run(["decision", "decide", "--id", "d1", "--agent", "alex", "--choose", "b"], tmp_path).returncode != 0
    ok(["decision", "open", "--id", "d3", "--agent", "planner", "--question", "Revisit X?", *OPTS], tmp_path)
    ok(["decision", "supersede", "--id", "d3", "--old", "d1"], tmp_path)
    assert run(["decision", "supersede", "--id", "d1", "--old", "d3"], tmp_path).returncode != 0   # cycle
    assert ok(["validate"], tmp_path).returncode == 0
    assert "superseded 1" in ok(["report"], tmp_path).stdout


def test_log_refuses_an_unlogged_decision(tmp_path):
    setup(tmp_path)
    r = run(["log", "--activity", "x", "--agent", "planner", "--used-decision", "nope"], tmp_path)
    assert r.returncode != 0 and "not logged" in r.stdout + r.stderr


def test_validate_names_each_defect_of_the_bad_fixture(tmp_path):
    (tmp_path / "provenance.ttl").write_text(BAD.read_text(encoding="utf-8"), encoding="utf-8")
    r = run(["validate"], tmp_path)
    out = r.stdout
    assert r.returncode != 0
    for needle in ("malformed", "incomplete", "did not offer", "not a registered human", "supersedes links"):
        assert needle in out, (needle, out)
