# aiprov

<img src="assets/aiprov-icon.png" alt="aiprov logo: a white salmon leaping up a waterfall in a teal-to-blue circle" width="120" align="right">

Domain-agnostic **AI provenance over W3C PROV-O**: who (human, AI model, tool) did what to an
artefact, with inference telemetry and a verification ladder whose top rungs only humans may grant.
Works for code, documents, data pipelines, CAD, AAS submodels — any AI-in-the-loop artefact.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23651333.svg)](https://doi.org/10.5281/zenodo.23651333)

**A demo graph, explained:** https://noheton.github.io/aiprov/

Namespace: `https://w3id.org/aiprov/ns#` · Generalised from
[F(AI)²R](https://github.com/noheton/f-ai-r) (arXiv:2607.25637).

## Install
```bash
uv add "aiprov @ git+https://github.com/noheton/aiprov@v0.2.0"   # or: pip install git+…@v0.2.0
```

## Use
```bash
provlog --base https://your.org/prov/ init
provlog --base https://your.org/prov/ agent --id alice --type human --name "Alice" --orcid 0000-…
provlog --base https://your.org/prov/ agent --id gpt --type ai --model gpt-x --provider Acme
provlog --base https://your.org/prov/ log --activity draft-1 --pass authoring --agent gpt \
        --generated doc.md --used notes.md --input-tokens 1200 --output-tokens 800
provlog --base https://your.org/prov/ claim --id c1 --text "…" --parent draft-1 --agent gpt --state ai-confirmed
provlog --base https://your.org/prov/ validate      # exit 1 on parentless claims or AI-granted human rungs
aiprov-dashboard provenance.ttl -o dashboard.html
```
Two invariants are enforced by `validate`: **no parentless claim**, and **human-only rungs**
(`human-confirmed`, `human-read`) are never granted by an AI agent.

## Layout
`schema/` vocabulary · `src/aiprov/` CLI · `docs/attributes.md` attribute catalogue ·
`tests/` with a synthetic example graph as fixture.

## Status
0.2.0 (2026-10-25) adds multi-agent orchestration, sharded logging and the human-only check in `claim` and
`source`; 0.1.0 packaged the skill bundle unchanged. The open schema proposals are planned for 0.3.0 (see CHANGELOG).
Releases are archived on Zenodo. Issues and pull requests welcome; the vocabulary is meant to be co-owned by
the systems that depend on it.

## Cite
Archived on Zenodo. Cite all versions with the concept DOI [10.5281/zenodo.23651333](https://doi.org/10.5281/zenodo.23651333), or a version:
0.2.0 [10.5281/zenodo.23651340](https://doi.org/10.5281/zenodo.23651340), 0.1.0 [10.5281/zenodo.23651334](https://doi.org/10.5281/zenodo.23651334). See `CITATION.cff`.

*AI note: repository scaffolded with AI assistance and logged in its own `provenance.ttl`; reviewed by the author.*
