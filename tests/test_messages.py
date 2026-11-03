"""Conversations between agents: channels and messages, hash by default (issue 43)."""
import hashlib, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOOD = ROOT / "tests" / "fixtures" / "message-thread.ttl"
BAD = ROOT / "tests" / "fixtures" / "message-bad.ttl"
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
    ok(["agent", "--id", "planner", "--type", "ai", "--model", "m-1"], tmp_path)
    ok(["agent", "--id", "reviewer", "--type", "ai", "--model", "m-2"], tmp_path)


def thread(tmp_path):
    setup(tmp_path)
    ok(["message", "--id", "m1", "--channel", "team", "--agent", "planner", "--text", "Plan: parser first.",
        "--keep-text", "--platform", "chat", "--channel-class", "internal", "--sent-at", "2026-11-01T09:00:00+00:00",
        "--refers-to", "https://example.org/tracker/issues/7"], tmp_path)
    ok(["message", "--id", "m2", "--channel", "team", "--agent", "reviewer", "--text", "Agreed.",
        "--reply-to", "m1"], tmp_path)
    ok(["message", "--id", "m3", "--channel", "team", "--agent", "planner", "--text", "secret", "--reply-to", "m2"], tmp_path)
    ok(["log", "--activity", "revise", "--agent", "planner", "--used-message", "m2"], tmp_path)


def test_thread_validates_and_hash_is_the_default(tmp_path):
    thread(tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0
    ttl = (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    assert "Plan: parser first." in ttl                      # kept on request
    assert "Agreed." not in ttl and "secret" not in ttl       # hash only by default
    assert hashlib.sha256(b"secret").hexdigest() in ttl
    assert "recordedAtTime" in ttl and ttl.count("sentAt") >= 1
    rep = ok(["report"], tmp_path).stdout
    assert "3 messages, text kept for 1" in rep


def test_no_sent_at_is_not_invented(tmp_path):
    thread(tmp_path)
    from rdflib import Graph, Namespace
    g = Graph(); g.parse(tmp_path / "provenance.ttl", format="turtle")
    sent = list(g.triples((None, Namespace("https://w3id.org/aiprov/ns#").sentAt, None)))
    assert len(sent) == 1 and str(sent[0][0]).endswith("/message/m1")   # only m1 was given a time


def test_log_refuses_an_unlogged_message(tmp_path):
    setup(tmp_path)
    r = run(["log", "--activity", "x", "--agent", "planner", "--used-message", "nope"], tmp_path)
    assert r.returncode != 0 and "not logged" in r.stdout + r.stderr


def test_message_refusals_leave_the_file_unchanged(tmp_path):
    thread(tmp_path)
    before = (tmp_path / "provenance.ttl").read_bytes()
    for args in (["--id", "x1", "--agent", "ghost", "--text", "t"],                       # unregistered sender
                 ["--id", "x2", "--agent", "planner", "--text", "t", "--reply-to", "zz"],  # reply target unknown
                 ["--id", "m1", "--agent", "planner", "--text", "t"],                      # append-only
                 ["--id", "x3", "--agent", "planner"],                                      # neither text nor hash
                 ["--id", "x4", "--agent", "planner", "--text", "t", "--content-hash", "sha256:" + "0" * 64],
                 ["--id", "x5", "--agent", "planner", "--content-hash", "abc"],             # malformed hash
                 ["--id", "x6", "--agent", "planner", "--content-hash", "sha256:" + "0" * 64, "--keep-text"],
                 ["--id", "x7", "--agent", "planner", "--text", "t", "--channel-class", "public"]):  # class is write-once
        r = run(["message", "--channel", "team", *args], tmp_path)
        assert r.returncode != 0 and "Traceback" not in r.stdout + r.stderr, (args, r.stdout, r.stderr)
    assert (tmp_path / "provenance.ttl").read_bytes() == before


def test_content_hash_without_text_is_accepted(tmp_path):
    setup(tmp_path)
    ok(["message", "--id", "h1", "--channel", "c", "--agent", "planner", "--content-hash", "sha256:" + "a" * 64], tmp_path)
    assert ok(["validate"], tmp_path).returncode == 0


def test_keeping_text_in_a_confidential_or_unclassed_channel_warns(tmp_path):
    setup(tmp_path)
    ok(["message", "--id", "k1", "--channel", "open", "--agent", "planner", "--text", "a", "--keep-text"], tmp_path)
    ok(["message", "--id", "k2", "--channel", "closed", "--agent", "planner", "--text", "b", "--keep-text",
        "--channel-class", "confidential"], tmp_path)
    v = ok(["validate"], tmp_path)                            # a warning, never a failure
    assert "[WARN] message text kept in a channel above internal or of unknown class: 2" in v.stdout


def test_fixture_thread_validates(tmp_path):
    shutil.copy(GOOD, tmp_path / "provenance.ttl")
    v = run(["validate"], tmp_path)
    assert v.returncode == 0, v.stdout + v.stderr
    assert "messages without a sender: 0" in v.stdout


def test_bad_fixture_fails_each_rule_once(tmp_path):
    shutil.copy(BAD, tmp_path / "provenance.ttl")
    v = run(["validate"], tmp_path)
    assert v.returncode != 0
    assert "[FAIL] agents referenced but not registered: 1" in v.stdout
    assert "[FAIL] replies to a message that is not in this graph: 1" in v.stdout
    assert "[FAIL] messages without a content hash, or whose kept text does not match it: 1" in v.stdout


def test_tampered_kept_text_fails_the_hash_rule(tmp_path):
    thread(tmp_path)
    p = tmp_path / "provenance.ttl"
    p.write_text(p.read_text(encoding="utf-8").replace("Plan: parser first.", "Plan: parser last."), encoding="utf-8")
    v = run(["validate"], tmp_path)
    assert v.returncode != 0 and "does not match it: 1" in v.stdout


def test_migration_stamps_and_adds_the_message_terms(tmp_path):
    fx = ROOT / "tests" / "fixtures" / "versions" / "v0.2.0.ttl"
    shutil.copy(fx, tmp_path / "provenance.ttl")
    assert ok(["migrate"], tmp_path).returncode == 0
    assert "aiprov:Message" in (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
