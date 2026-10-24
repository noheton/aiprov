"""extract --dashboard renders the extract through the packaged dashboard module."""
import pathlib, subprocess, sys

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "example-graph.ttl"


def test_extract_dashboard_writes_html(tmp_path):
    out, html = tmp_path / "extract.ttl", tmp_path / "dash.html"
    r = subprocess.run(
        [sys.executable, "-m", "aiprov.provlog", "extract", "--graph", str(FIXTURE),
         "--seed-types", "Claim", "-o", str(out), "--dashboard", str(html)],
        cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file()
    text = html.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>") and "__DATA__" not in text
