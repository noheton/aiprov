"""Harness identity, model variant and an unknown model with a reason (issue 23)."""
import json, pathlib, subprocess, sys

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


def cfg(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def chash(tmp_path, name, obj, hid):
    ok(["harness", "--id", hid, "--kind", "coding-agent-cli", "--version", "1.0",
        "--config-file", cfg(tmp_path, name, obj)], tmp_path)
    ttl = (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    block = ttl.split(f"harness/{hid}>", 1)[1].split(" .", 1)[0]
    return block.split('configHash "', 1)[1].split('"', 1)[0]


def test_secret_value_does_not_change_the_hash_but_rule_order_does(tmp_path):
    setup(tmp_path)
    base = {"rules": ["allow:read", "deny:write"], "api_key": "AAA", "url": "https://x.example/a"}
    h1 = chash(tmp_path, "c1.json", base, "h1")
    h2 = chash(tmp_path, "c2.json", {**base, "api_key": "BBB"}, "h2")
    h3 = chash(tmp_path, "c3.json", {**base, "rules": ["deny:write", "allow:read"]}, "h3")
    assert h1 == h2 and h1 != h3
    ttl = (tmp_path / "provenance.ttl").read_text(encoding="utf-8")
    assert "AAA" not in ttl and "BBB" not in ttl and "x.example" not in ttl
    assert "aiprov-config/1" in ttl


def test_two_harnesses_model_switch_validate_and_report(tmp_path):
    setup(tmp_path)
    ok(["agent", "--id", "m2", "--type", "ai", "--model", "m-other"], tmp_path)
    ok(["harness", "--id", "cli", "--kind", "coding-agent-cli", "--version", "2.1"], tmp_path)
    ok(["harness", "--id", "chat", "--kind", "portal-chat"], tmp_path)
    ok(["log", "--activity", "a1", "--agent", "m1", "--session", "s1", "--harness", "cli", "--model-variant", "low"], tmp_path)
    ok(["log", "--activity", "a2", "--agent", "m2", "--session", "s1", "--harness", "cli", "--model-variant", "max"], tmp_path)
    ok(["log", "--activity", "b1", "--agent", "m1", "--harness", "chat",
        "--model-unknown-reason", "not reported by the harness"], tmp_path)
    v = ok(["validate"], tmp_path).stdout
    assert "viaHarness targets that are not registered harnesses: 0" in v
    rep = ok(["report"], tmp_path).stdout
    assert "-- harnesses --" in rep and "coding-agent-cli, 2 activities, variants low, max" in rep
    assert "portal-chat, 1 activities, model unknown 1" in rep


def test_unregistered_harness_is_refused_and_validate_fails_on_a_dangling_one(tmp_path):
    setup(tmp_path)
    r = run(["log", "--activity", "a1", "--agent", "m1", "--harness", "nope"], tmp_path)
    assert r.returncode != 0 and "not registered" in (r.stdout + r.stderr)
    ok(["log", "--activity", "a1", "--agent", "m1"], tmp_path)
    ttl = tmp_path / "provenance.ttl"
    ttl.write_text(ttl.read_text(encoding="utf-8") + f"\n<{BASE}activity/a1> <https://w3id.org/aiprov/ns#viaHarness> <{BASE}harness/ghost> .\n",
                   encoding="utf-8")
    v = run(["validate"], tmp_path)
    assert v.returncode != 0 and "[FAIL] viaHarness targets that are not registered harnesses: 1" in v.stdout


def test_activity_via_harness_without_model_or_reason_warns_only(tmp_path):
    setup(tmp_path)
    ok(["agent", "--id", "t1", "--type", "tool"], tmp_path)
    ok(["harness", "--id", "cli", "--kind", "batch"], tmp_path)
    ok(["log", "--activity", "a1", "--agent", "t1", "--harness", "cli"], tmp_path)
    v = run(["validate"], tmp_path)
    assert v.returncode == 0 and "[WARN] activities via a harness with neither a model nor a stated reason: 1" in v.stdout


def test_harness_values_are_write_once(tmp_path):
    setup(tmp_path)
    ok(["harness", "--id", "cli", "--kind", "coding-agent-cli", "--version", "1.0"], tmp_path)
    before = (tmp_path / "provenance.ttl").read_bytes()
    r = run(["harness", "--id", "cli", "--kind", "coding-agent-cli", "--version", "2.0"], tmp_path)
    assert r.returncode != 0 and "append-only" in (r.stdout + r.stderr)
    r = run(["harness", "--id", "cli2", "--kind", "unknown-kind"], tmp_path)
    assert r.returncode != 0
    assert (tmp_path / "provenance.ttl").read_bytes() == before
