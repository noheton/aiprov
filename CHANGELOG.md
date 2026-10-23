# Changelog

## 0.1.0 — 2026-10-23
First packaged release. Content identical to the aiprov skill bundle generalised from F(AI)²R:
- `schema/aiprov-schema.ttl` — agents, activities, telemetry attributes, claims, sources,
  verification ladder (`unverified … human-read`; `source-vendored` present, see 0.2 plan).
- `provlog` CLI: init, agent, log, claim, validate, report, search, source, promote, extract.
- `aiprov-dashboard`: self-contained HTML ledger from a graph.
- Namespace `https://w3id.org/aiprov/ns#` (w3id registration pending at release time).

## 0.2.0 — planned
Session types; vendoring as a property (`vendoredFile`, rung deprecated, migration script);
model identity for local models; OTel ingest; source attribution and self-citation rule.
Tracked as issues; nothing lands before the first external consumer has reviewed #0.
