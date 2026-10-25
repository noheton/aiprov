"""Build the aiprov pitch page.

Runs a small invented scenario with the real `provlog`, checks that every command behaves as the page says (the build
fails otherwise), draws the resulting graph as SVG and writes `public/`: index.html, demo.ttl, dashboard.html and the
badge. No external scripts, fonts or trackers.

usage: uv run python site/build.py [--out public]

Deployed to GitHub Pages by .github/workflows/pages.yml; the demo runs with the code of the checked-out commit.
"""

from __future__ import annotations

import argparse
import html
import importlib.metadata as md
import json
import math
import os
import re
import shutil
import string
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import rdflib
from rdflib.namespace import FOAF, PROV, RDF, RDFS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = "https://example.org/demo/"
AIPROV = rdflib.Namespace("https://w3id.org/aiprov/ns#")
NOTES = "Benchmark notes: old parser 410 ms, new parser 190 ms on the sample set.\n"
REPORT = "# Parser report\n\nThe new parser is twice as fast.\nAll public functions are tested.\n"
HUMAN_READ = ["--state", "human-read"]

# (step on the page, provlog arguments, expected exit code)
SCENARIO = [
    (0, ["init"], 0),
    (1, ["agent", "--id", "alice", "--type", "human", "--name", "Alice Example", "--orcid", "0000-0002-1825-0097"], 0),
    (1, ["agent", "--id", "model-x", "--type", "ai", "--name", "Model X", "--model", "model-x",
         "--provider", "Example AI", "--acted-on-behalf-of", "alice"], 0),
    (2, ["log", "--activity", "draft-report", "--pass", "authoring", "--agent", "model-x",
         "--label", "Draft the report from the notes", "--used", "notes.md", "--generated", "report.md",
         "--input-tokens", "1200", "--output-tokens", "800"], 0),
    (3, ["claim", "--id", "c-speed", "--text", "The new parser is twice as fast.", "--parent", "draft-report",
         "--agent", "model-x", "--state", "ai-confirmed"], 0),
    (3, ["claim", "--id", "c-tests", "--text", "All public functions are tested.", "--parent", "draft-report",
         "--agent", "model-x", "--state", "unverified"], 0),
    (4, ["promote", "--id", "c-speed", "--to", "human-confirmed", "--agent", "alice",
         "--note", "Re-ran the benchmark myself"], 0),
    (5, ["claim", "--id", "c-tests", "--text", "All public functions are tested.", "--parent", "draft-report",
         "--agent", "model-x", *HUMAN_READ], 1),
    (5, ["validate"], 0),
]

# Fixed positions (centre x, y) of every node the scenario creates; an unknown node fails the build.
LAYOUT = {
    "agent/alice": (115, 105),
    "agent/model-x": (115, 325),
    "activity/promote-c-speed-human-confirmed": (455, 105),
    "activity/draft-report": (455, 325),
    "source/notes-md": (455, 480),
    "claim/c-speed": (835, 165),
    "claim/c-tests": (835, 305),
    "entity/report-md": (835, 445),
}
SIZE = {"agent": (190, 70), "activity": (210, 62), "entity": (190, 60), "claim": (280, 72)}
FILL = {
    "agent": ("#fde9c9", "#c98a2b"),
    "activity": ("#dde7fb", "#4c6fbf"),
    "entity": ("#fff6cc", "#b89b2e"),
    "claim": ("#fff6cc", "#b89b2e"),
}
STATE_COLOUR = {
    "unverified": "#8a96a3", "needs-research": "#b0773a", "reference-resolved": "#5b8bd0",
    "ai-confirmed": "#2b86c5", "source-vendored": "#3c7fa0", "human-confirmed": "#2e9e6a", "human-read": "#1d7a4f",
}
LABEL_AT = {"wasGeneratedBy": 0.42}
SVG_STYLE = (
    "<style>"
    "text { font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Inter, Arial, sans-serif; }"
    ".nt { font-size: 15px; font-weight: 600; fill: #1b2733; } .ns { font-size: 12.5px; fill: #4a5a6a; }"
    ".pill { font-size: 11.5px; font-weight: 600; fill: #fff; } .edge { stroke: #5d6d7e; stroke-width: 1.5; }"
    ".lb { fill: #fff; opacity: 0.92; } .el { font-size: 11.5px; font-style: italic; fill: #4f5f70; }"
    ".mk { fill: #0fa3b1; } .mkt { font-size: 14px; font-weight: 700; fill: #fff; }"
    ".lt { font-size: 14px; font-weight: 600; fill: #1b2733; } .ls { font-size: 12.5px; fill: #1b2733; }"
    ".br { fill: none; stroke: #2e9e6a; stroke-width: 1.6; } .hl { font-size: 12.5px; font-weight: 600; fill: #2e9e6a; }"
    ".pp { fill: none; stroke: #2e9e6a; stroke-width: 1.6; stroke-dasharray: 5 4; } .pt { font-size: 12.5px; fill: #2e6b50; }"
    "</style>"
)
MARKERS = [(1, 40, 52), (2, 348, 292), (3, 1005, 235), (4, 348, 72)]


def run_scenario(work: Path) -> tuple[list[tuple[int, list[str], int, str]], Path]:
    (work / "notes.md").write_text(NOTES)
    (work / "report.md").write_text(REPORT)
    provlog = shutil.which("provlog")
    if not provlog:
        raise SystemExit("provlog not found; run with `uv run`")
    out = []
    for step, args, expected in SCENARIO:
        r = subprocess.run([provlog, "--base", BASE, *args], cwd=work, capture_output=True, text=True, check=False)
        if r.returncode != expected:
            raise SystemExit(f"provlog {' '.join(args)}: exit {r.returncode}, expected {expected}\n{r.stdout}{r.stderr}")
        out.append((step, args, r.returncode, (r.stdout + r.stderr).strip()))
    return out, work / "provenance.ttl"


def local(iri: rdflib.term.Node) -> str:
    return str(iri)[len(BASE):] if str(iri).startswith(BASE) else ""


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def boundary(kind: str, cx: float, cy: float, dx: float, dy: float) -> tuple[float, float]:
    """Point where a ray from the node centre in direction (dx, dy) leaves the node's shape."""
    w, h = SIZE[kind]
    if kind == "entity":
        t = 1 / math.hypot(dx / (w / 2), dy / (h / 2))
    else:
        t = min((w / 2) / abs(dx) if dx else math.inf, (h / 2) / abs(dy) if dy else math.inf)
    return cx + dx * t, cy + dy * t


def node_svg(kind: str, cx: float, cy: float, title: str, sub: str, tip: str, pill: str | None = None) -> str:
    w, h = SIZE[kind]
    fill, stroke = FILL[kind]
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    if kind == "agent":
        roof = 16
        pts = f"{x0},{y0 + roof} {cx},{y0} {x1},{y0 + roof} {x1},{y1} {x0},{y1}"
        shape = f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
        ty = cy + 6
    elif kind == "activity":
        shape = f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
        ty = cy
    elif kind == "entity":
        shape = f'<ellipse cx="{cx}" cy="{cy}" rx="{w / 2}" ry="{h / 2}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
        ty = cy
    else:
        shape = f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
        ty = cy - 6
    parts = [f"<g><title>{esc(tip)}</title>", shape,
             f'<text x="{cx}" y="{ty - 4}" text-anchor="middle" class="nt">{esc(title)}</text>',
             f'<text x="{cx}" y="{ty + 13}" text-anchor="middle" class="ns">{esc(sub)}</text>']
    if pill:
        pw = 9 + 7.1 * len(pill)
        colour = STATE_COLOUR.get(pill, "#666")
        parts.append(f'<rect x="{cx - pw / 2}" y="{y1 - 22}" width="{pw}" height="17" rx="8.5" fill="{colour}"/>')
        parts.append(f'<text x="{cx}" y="{y1 - 9.5}" text-anchor="middle" class="pill">{esc(pill)}</text>')
    parts.append("</g>")
    return "".join(parts)


def draw(g: rdflib.Graph) -> str:
    kinds: dict[str, str] = {}
    nodes: list[str] = []
    for s in set(g.subjects()):
        key = local(s)
        if not key or key.split("/")[0] not in {"agent", "activity", "source", "entity", "claim"}:
            continue
        if key not in LAYOUT:
            raise SystemExit(f"node without a place in the figure: {key}")
        cx, cy = LAYOUT[key]
        types = set(g.objects(s, RDF.type))
        name = str(g.value(s, FOAF.name) or "")
        if AIPROV.HumanAgent in types:
            kinds[key] = "agent"
            orcid = g.value(s, AIPROV.orcid)
            nodes.append(node_svg("agent", cx, cy, name, "HumanAgent, ORCID iD", f"{name}: a person, ORCID {orcid}"))
        elif AIPROV.AIAgent in types:
            kinds[key] = "agent"
            provider = g.value(s, AIPROV.provider)
            nodes.append(node_svg("agent", cx, cy, name, f"AIAgent, {provider}", f"{name}: an AI model ({g.value(s, AIPROV.model)})"))
        elif AIPROV.AuthoringPass in types or AIPROV.AuditPass in types:
            kinds[key] = "activity"
            kind = "AuthoringPass" if AIPROV.AuthoringPass in types else "AuditPass"
            tokens = g.value(s, AIPROV.totalTokens)
            if kind == "AuditPass":
                title, sub = "promotion of c-speed", "AuditPass, human-confirmed"
            else:
                title, sub = key.split("/", 1)[1], f"AuthoringPass, {int(tokens):,} tokens" if tokens else "AuthoringPass"
            nodes.append(node_svg("activity", cx, cy, title, sub, str(g.value(s, RDFS.label) or title)))
        elif AIPROV.Claim in types:
            kinds[key] = "claim"
            state = str(g.value(s, AIPROV.verificationState)).rsplit("/", 1)[-1]
            text = str(g.value(s, RDFS.label))
            nodes.append(node_svg("claim", cx, cy, text, f"claim {key.split('/', 1)[1]}", f"claim: {text} ({state})", pill=state))
        elif AIPROV.Source in types or AIPROV.Artefact in types:
            kinds[key] = "entity"
            path = str(g.value(s, AIPROV.filePath))
            digest = str(g.value(s, AIPROV.contentHash) or "")
            sub = f"Artefact, sha256 {digest.split(':')[-1][:8]}" if AIPROV.Artefact in types else "Source (input)"
            nodes.append(node_svg("entity", cx, cy, path, sub, f"{path}: {digest or 'used as input'}"))
    missing = set(LAYOUT) - set(kinds)
    if missing:
        raise SystemExit(f"figure expects nodes the graph does not have: {sorted(missing)}")

    edges: list[str] = []
    labels: list[str] = []
    for p in (PROV.actedOnBehalfOf, PROV.wasAssociatedWith, PROV.used, PROV.wasGeneratedBy):
        name = p.split("#")[-1]
        for s, o in g.subject_objects(p):
            a, b = local(s), local(o)
            if a not in kinds or b not in kinds:
                continue
            (ax, ay), (bx, by) = LAYOUT[a], LAYOUT[b]
            dx, dy = bx - ax, by - ay
            sx, sy = boundary(kinds[a], ax, ay, dx, dy)
            ex, ey = boundary(kinds[b], bx, by, -dx, -dy)
            edges.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" class="edge" marker-end="url(#arr)"/>')
            t = LABEL_AT.get(name, 0.5)
            lx, ly = sx + (ex - sx) * t, sy + (ey - sy) * t
            lw = 6.3 * len(name) + 10
            labels.append(f'<rect x="{lx - lw / 2:.1f}" y="{ly - 9:.1f}" width="{lw:.1f}" height="17" rx="4" class="lb"/>'
                          f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="middle" class="el">{name}</text>')

    markers = [f'<circle cx="{x}" cy="{y}" r="13" class="mk"/><text x="{x}" y="{y + 5}" text-anchor="middle" class="mkt">{n}</text>'
               for n, x, y in MARKERS]

    # The ladder: seven steps, the top two for humans only.
    ladder_states = sorted(
        (int(g.value(s, AIPROV.ladderPosition)), str(s).rsplit("/", 1)[-1], str(g.value(s, RDFS.label)))
         for s in g.subjects(RDF.type, AIPROV.VerificationState))
    lx0, ly0, gap = 20, 570, 8
    bw = (1040 - 2 * lx0 - 6 * gap) / 7
    ladder = ['<text x="20" y="548" class="lt">The verification ladder</text>']
    centres = {}
    for pos, sid, label in ladder_states:
        x = lx0 + pos * (bw + gap)
        centres[sid] = x + bw / 2
        human = pos >= 5
        ladder.append(f'<rect x="{x:.1f}" y="{ly0}" width="{bw:.1f}" height="40" rx="6" '
                      f'fill="{"#e3f4ec" if human else "#eef2f6"}" stroke="{STATE_COLOUR[sid]}" stroke-width="1.6"/>'
                      f'<text x="{x + bw / 2:.1f}" y="{ly0 + 25}" text-anchor="middle" class="ls">{esc(label)}</text>')
    hx0, hx1 = lx0 + 5 * (bw + gap), lx0 + 7 * bw + 6 * gap
    ladder.append(f'<path d="M{hx0:.1f},{ly0 - 6} V{ly0 - 14} H{hx1:.1f} V{ly0 - 6}" class="br"/>'
                  f'<text x="{(hx0 + hx1) / 2:.1f}" y="{ly0 - 20}" text-anchor="middle" class="hl">humans only</text>'
                  f'<circle cx="{hx1 - 12:.1f}" cy="{ly0 - 26}" r="13" class="mk"/>'
                  f'<text x="{hx1 - 12:.1f}" y="{ly0 - 21}" text-anchor="middle" class="mkt">5</text>')
    a3, a5, a0 = centres["ai-confirmed"], centres["human-confirmed"], centres["unverified"]
    ladder.append(f'<path d="M{a3:.1f},{ly0 + 44} C{a3:.1f},{ly0 + 80} {a5:.1f},{ly0 + 80} {a5:.1f},{ly0 + 46}" class="pp" marker-end="url(#arrg)"/>'
                  f'<text x="{(a3 + a5) / 2:.1f}" y="{ly0 + 92}" text-anchor="middle" class="pt">c-speed, promoted by Alice (4)</text>'
                  f'<text x="{a0:.1f}" y="{ly0 + 62}" text-anchor="middle" class="pt">c-tests stays here</text>')

    defs = ('<defs><marker id="arr" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#5d6d7e"/></marker>'
            '<marker id="arrg" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#2e9e6a"/></marker></defs>')
    return ('<svg viewBox="0 0 1040 680" role="img" aria-labelledby="fig-title" xmlns="http://www.w3.org/2000/svg">'
            '<title id="fig-title">The demo graph: Alice and Model X, the draft and the promotion, two files, two claims, '
            'and the verification ladder</title>' + SVG_STYLE + defs + "".join(edges) + "".join(labels) + "".join(nodes)
            + "".join(markers) + "".join(ladder) + "</svg>")


def shown(args: list[str], width: int = 78) -> str:
    """The command as a reader would type it, broken before an option with a backslash when the line gets long."""
    words = [f'"{a}"' if " " in a else a for a in args]
    groups: list[str] = []
    for w in words:
        if groups and not w.startswith("--") and groups[-1].startswith("--") and " " not in groups[-1]:
            groups[-1] += " " + w
        else:
            groups.append(w)
    lines, line = [], "provlog"
    for grp in groups:
        if len(line) + 1 + len(grp) > width and line.strip() != "provlog":
            lines.append(line + " \\")
            line = "    " + grp
        else:
            line += " " + grp
    return "\n".join([*lines, line])


def terminal(results: list[tuple[int, list[str], int, str]]) -> str:
    lines = []
    for _, args, code, output in results:
        lines.append(f'<span class="pr">$</span> {esc(shown(args))}')
        for ln in output.splitlines():
            cls = "bad" if ln.startswith("REFUSED") else "ok" if ln.startswith("[ OK ]") else "out"
            lines.append(f'<span class="{cls}">{esc(ln)}</span>')
        if code:
            lines.append(f'<span class="bad">(exit {code})</span>')
    return "\n".join(lines)


def aiprov_version() -> str:
    """Package version and commit: from the git install record, the CI environment or the working tree."""
    dist = md.distribution("aiprov")
    try:
        commit = json.loads(dist.read_text("direct_url.json") or "{}").get("vcs_info", {}).get("commit_id", "")
    except json.JSONDecodeError:
        commit = ""
    if not commit:
        commit = os.environ.get("GITHUB_SHA", "")
    if not commit:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        commit = r.stdout.strip()
    return f"{dist.version}" + (f" (git {commit[:7]})" if commit else "")


def citation(version: str) -> dict:
    """DOIs, title, authors and year from CITATION.cff, so the page never disagrees with the citation metadata."""
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    concept = re.search(r"^doi:\s*(\S+)", text, re.MULTILINE)
    if not concept:
        return {}
    versions = {v: d for d, v in re.findall(r'value:\s*(\S+)\s*\n\s*description:\s*"Version ([^"]+)"', text)}
    block = text.split("authors:", 1)[1].split("\nreferences:", 1)[0]
    return {
        "concept": concept.group(1),
        "version_doi": versions.get(version, ""),
        "title": re.search(r'^title:\s*"?(.*?)"?\s*$', text, re.MULTILINE).group(1),
        "authors": re.findall(r"family-names:\s*(.+)\n\s*given-names:\s*(.+)", block),
        "year": re.search(r"^date-released:\s*(\d{4})", text, re.MULTILINE).group(1),
    }


def cite_parts(c: dict, version: str, repo: str) -> dict[str, str]:
    if not c:
        return {"cite_link": "", "doi_badge": "", "cite_section": ""}
    concept, vdoi = c["concept"], c["version_doi"]
    names = ", ".join(f"{fam.strip()}, {''.join(p[0] + '.' for p in giv.split())}" for fam, giv in c["authors"])
    doi = vdoi or concept
    ver = f" (Version {esc(version)})" if vdoi else ""
    return {
        "cite_link": f'<link rel="cite-as" href="https://doi.org/{esc(concept)}">',
        "doi_badge": (f'<a class="badge" href="https://doi.org/{esc(concept)}" title="DOI for all versions">'
                      f"<span>DOI</span><span>{esc(concept)}</span></a>"),
        "cite_section": (
            '<section>\n<h2>Cite</h2>\n'
            f'<p class="ref">{esc(names)} ({esc(c["year"])}). <em>{esc(c["title"])}</em>{ver} [Software]. Zenodo. '
            f'<a href="https://doi.org/{esc(doi)}">https://doi.org/{esc(doi)}</a></p>\n'
            f'<p>All versions: <a href="https://doi.org/{esc(concept)}">https://doi.org/{esc(concept)}</a>. '
            f'Citation metadata: <a href="{esc(repo)}/blob/main/CITATION.cff">CITATION.cff</a>.</p>\n</section>'),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="public")
    out = Path(ap.parse_args().out)
    with tempfile.TemporaryDirectory() as tmp:
        results, ttl = run_scenario(Path(tmp))
        g = rdflib.Graph().parse(ttl, format="turtle")
        figure = draw(g)
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        shutil.copy(ttl, out / "demo.ttl")
        dashboard = shutil.which("aiprov-dashboard")
        if dashboard:
            subprocess.run([dashboard, str(ttl), "-o", str(out / "dashboard.html")], check=True, capture_output=True)
    shutil.copy(ROOT / "assets" / "aiprov-icon.png", out / "aiprov-icon.png")
    server, name = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY")
    repo = f"{server}/{name}" if server and name else "https://github.com/noheton/aiprov"
    version = md.distribution("aiprov").version
    page = string.Template((HERE / "page.html").read_text()).substitute(
        **cite_parts(citation(version), version, repo),
        figure=figure,
        terminal=terminal(results),
        version=esc(aiprov_version()),
        built=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        dashboard='<a href="dashboard.html">the dashboard</a>' if (out / "dashboard.html").exists() else "the dashboard",
        repo_graph=f'<a href="{esc(repo)}/blob/main/provenance.ttl">provenance.ttl</a>',
    )
    (out / "index.html").write_text(page)
    print(f"wrote {out}/: {', '.join(sorted(p.name for p in out.iterdir()))}")


if __name__ == "__main__":
    main()
