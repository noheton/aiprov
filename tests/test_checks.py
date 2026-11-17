"""Checks: questions put per claim and source section, answered by humans only (issue 5)."""
import os
import subprocess
import sys

BASE = "https://example.org/prov/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "PROV_ACTOR": ""}, check=False)


def setup(tmp_path):
    assert run(["init"], tmp_path).returncode == 0
    assert run(["agent", "--id", "anna", "--type", "human", "--name", "Anna"], tmp_path).returncode == 0
    assert run(["agent", "--id", "bot", "--type", "ai", "--model", "m", "--provider", "p", "--acted-on-behalf-of", "anna"], tmp_path).returncode == 0
    assert run(["log", "--activity", "a1", "--pass", "authoring", "--agent", "bot", "--label", "x"], tmp_path).returncode == 0
    r = run(["claim", "--id", "c1", "--text", "t", "--parent", "a1", "--agent", "bot", "--state", "unverified"], tmp_path)
    assert r.returncode == 0, r.stderr
    r = run(["source", "--id", "s1", "--url", "https://example.org/s", "--agent", "bot"], tmp_path)
    assert r.returncode == 0, r.stderr
    (tmp_path / "q.txt").write_text("quote")
    r = run(["check", "--id", "k1", "--claim", "c1", "--source", "s1", "--locator", "sec 2",
             "--question", "Does it say so?", "--excerpt-file", "q.txt", "--agent", "bot"], tmp_path)
    assert r.returncode == 0, r.stderr


def test_prepare_answer_and_gate(tmp_path):
    setup(tmp_path)
    assert run(["validate"], tmp_path).returncode == 0
    assert "quote" not in (tmp_path / "provenance.ttl").read_text()
    assert run(["promote", "--id", "c1", "--to", "human-read", "--agent", "anna"], tmp_path).returncode != 0
    r = run(["answer", "--check", "k1", "--answer", "yes", "--agent", "bot"], tmp_path)
    assert r.returncode != 0
    assert run(["answer", "--check", "k1", "--answer", "yes", "--agent", "anna"], tmp_path).returncode == 0
    assert run(["answer", "--check", "k1", "--answer", "no", "--agent", "anna"], tmp_path).returncode != 0
    assert run(["promote", "--id", "c1", "--to", "human-read", "--agent", "anna"], tmp_path).returncode == 0
    assert run(["validate"], tmp_path).returncode == 0


def test_partly_blocks_promotion(tmp_path):
    setup(tmp_path)
    assert run(["answer", "--check", "k1", "--answer", "partly", "--agent", "anna"], tmp_path).returncode == 0
    assert run(["promote", "--id", "c1", "--to", "human-read", "--agent", "anna"], tmp_path).returncode != 0
