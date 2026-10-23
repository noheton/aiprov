# Contributing

aiprov is meant to be co-owned by the systems that depend on it. Issues and pull requests are
welcome; schema changes follow one rule: **extend, don't fork** — additive changes land in a minor
release, anything that changes the meaning of an existing term gets a deprecation first and a
migration script.

- Discuss schema changes in an issue before a PR.
- Every PR runs the tests; a schema change adds or updates a fixture.
- The repository logs its own AI-assisted work in `provenance.ttl` (`provlog log …`); please do the
  same for AI-assisted contributions, and never grant `human-confirmed`/`human-read` from an AI agent.
- By contributing you agree to the MIT licence.

AI agents and humans working with AI follow `AGENTS.md`: the session is logged in `provenance.ttl`, and CI validates the
graph (job `provenance`; the test `tests/test_repository_provenance.py` does the same locally).
