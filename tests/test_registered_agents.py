"""An agent must be registered with `provlog agent` before log, claim, source or promote name it (issue 21)."""
import pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "example-graph.ttl"
BAD = ROOT / "tests" / "fixtures" / "unregistered-agent.ttl"
BASE = "https://example.org/prov/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def graph(tmp_path):
    shutil.copy(FIX, tmp_path / "provenance.ttl")
    return tmp_path / "provenance.ttl"


def refused(r):
    out = r.stdout + r.stderr
    return r.returncode != 0 and "not registered" in out and "provlog agent" in out and "Traceback" not in out


def test_log_claim_source_promote_refuse_an_unregistered_agent(tmp_path):
    ttl = graph(tmp_path)
    before = ttl.read_bytes()
    for args in (
        ["log", "--activity", "a-ghost", "--pass", "authoring", "--agent", "ghost", "--generated", "x.md"],
        ["claim", "--id", "c-ghost", "--text", "t", "--parent", "draft-1", "--agent", "ghost"],
        ["source", "--id", "s-ghost", "--url", "https://example.org/a", "--agent", "ghost"],
        ["promote", "--id", "src1", "--to", "retrieved", "--agent", "ghost"],
    ):
        r = run(args, tmp_path)
        assert refused(r), (args, r.stdout, r.stderr)
    assert ttl.read_bytes() == before


def test_registered_agents_of_all_three_types_are_unaffected(tmp_path):
    graph(tmp_path)
    for aid, typ in (("ai-1", "ai"), ("person-1", "human"), ("tool-1", "tool")):
        assert run(["agent", "--id", aid, "--type", typ], tmp_path).returncode == 0
        r = run(["log", "--activity", f"a-{aid}", "--agent", aid], tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        r = run(["claim", "--id", f"c-{aid}", "--text", "t", "--parent", f"a-{aid}", "--agent", aid], tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        r = run(["source", "--id", f"s-{aid}", "--url", "https://example.org/a", "--agent", aid], tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
    assert run(["validate"], tmp_path).returncode == 0


def test_log_and_source_without_agent_still_work(tmp_path):
    graph(tmp_path)
    assert run(["source", "--id", "s-none", "--url", "https://example.org/a"], tmp_path).returncode == 0


def test_validate_fails_on_a_graph_with_an_unregistered_agent(tmp_path):
    shutil.copy(BAD, tmp_path / "provenance.ttl")
    r = run(["validate"], tmp_path)
    assert r.returncode != 0
    assert "[FAIL] agents referenced but not registered: 1" in r.stdout, r.stdout
    assert "agent/ghost" in r.stdout


def test_merge_rejects_a_shard_that_references_an_unregistered_agent(tmp_path):
    graph(tmp_path)
    d = tmp_path / "shard"
    d.mkdir()
    shutil.copy(BAD, d / "provenance.ttl")
    r = run(["merge", "--from", str(d / "provenance.ttl")], tmp_path)
    assert r.returncode != 0 and "REJECTED" in r.stdout and "not registered" in r.stdout, r.stdout + r.stderr
