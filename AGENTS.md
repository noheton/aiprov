# Rules for AI agents working in this repository

aiprov is the provenance toolchain, so the repository works the way it asks others to work: every AI-assisted
change is recorded in its own graph (`provenance.ttl`) and the graph is validated in CI. Humans follow the same
rules (see `CONTRIBUTING.md`).

## Before and after a session
1. Read `CONTRIBUTING.md` and this file. Schema changes need an issue first, then a pull request with a fixture.
2. Work on a branch, never on `main`. Run `uv run pytest -q` before you push.
3. Record the session in the graph, after the content commit, with the commit hash:
   `uv run provlog --base https://w3id.org/aiprov/prov/ log --activity <slug> --pass authoring|audit|build|repair --agent <agent-id> --commit <hash> --session-id <id> --label "..." --generated <path>`
   Register a new agent or model first with `provlog agent`. Telemetry (tokens, cost) is recorded only when the
   tool or gateway reports it; it is never estimated.
4. Every non-trivial statement an AI contributes becomes a claim: `provlog claim --state unverified|ai-confirmed`.
   An AI never sets `human-confirmed` or `human-read`: `provlog claim`, `source` and `promote` refuse it unless the agent is a registered human, and `merge` rejects a shard that contains it.
5. Run `uv run provlog --base https://w3id.org/aiprov/prov/ validate` and commit the graph in its own commit whose
   message ends with the trailer `Aiprov-Activity: https://w3id.org/aiprov/prov/activity/<slug>`.

## Commits
- Conventional prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), one concern per commit.
- AI-assisted commits carry `Co-Authored-By: <model> <noreply@anthropic.com>` (or the matching address).
- Sub-agents never commit or push; the session that dispatched them commits and logs them.

## This repository is public
- Nothing from private or internal sources goes in: no hostnames, issue numbers, document text or data of other
  projects. Tests and fixtures use invented data (see `tests/fixtures/`).
- No personal data beyond the author's public name and ORCID iD.
- Do not publish, release or change repository settings without the owner's decision.
