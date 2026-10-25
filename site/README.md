# Demo page

The page at https://noheton.github.io/aiprov/: a short pitch, a demo graph and its explanation.

`build.py` runs a small invented scenario with `provlog` from this repository (nine commands: two agents, a draft, two
claims, a human promotion, a refused attempt, `validate`), fails if any command behaves differently from what the page
says, draws the resulting graph as SVG and fills `page.html`. Output: `index.html`, `demo.ttl`, `dashboard.html` (built
by `aiprov-dashboard`) and the badge. No external scripts, fonts or trackers.

```bash
uv run python site/build.py --out public    # then open public/index.html
```

`.github/workflows/pages.yml` builds it on every pull request and deploys it from `main`. The node positions of the
figure are fixed in `LAYOUT`; a node the scenario creates without a place there stops the build.
