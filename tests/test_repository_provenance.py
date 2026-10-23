"""The repository follows its own method: its provenance graph must validate."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_repository_graph_validates():
    r = subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", "https://w3id.org/aiprov/prov/", "validate"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
