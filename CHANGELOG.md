# Changelog

## 0.1.0 — 2026-10-23
First packaged release. Content identical to the aiprov skill bundle generalised from F(AI)²R:
- `schema/aiprov-schema.ttl` — agents, activities, telemetry attributes, claims, sources,
  verification ladder (`unverified … human-read`; `source-vendored` present, see 0.2 plan).
- `provlog` CLI: init, agent, log, claim, validate, report, search, source, promote, extract.
- `aiprov-dashboard`: self-contained HTML ledger from a graph.
- Namespace `https://w3id.org/aiprov/ns#` (w3id registration pending at release time).

## Unreleased — orchestration (multi-agent runs)
Additive; legacy graphs validate unchanged.
- Schema: `aiprov:Orchestration` (a `prov:Activity`), `aiprov:plannedRole`, `aiprov:plannedAgent`, `aiprov:role`.
  Delegation uses PROV-O: `prov:actedOnBehalfOf` (agent → orchestrator), `prov:wasInformedBy` (sub-activity → orchestration).
- `provlog agent --acted-on-behalf-of`; `provlog log --orchestration --planned-role --planned-agent`,
  `--informed-by`, `--role`. The logger refuses planned agents that are not registered yet and sub-activities
  outside the declared plan (agent or role).
- `validate`: dangling `wasInformedBy`, sub-activities outside the plan, sub-activities logged before their
  orchestration (all FAIL). `report`: sub-activities and reported tokens per orchestration, so a cascade is not
  counted as many independent AI activities.
- Found by a multi-agent review of this change (three lenses, adversarial verification) and fixed: re-logging an
  orchestration or any activity linked to one is refused (it widened the plan and made valid runs fail), an activity
  cannot be informed by itself, and omitting `--agent`/`--role` no longer bypasses a declared plan (logger and
  validator).

## 0.2.0 — planned
Session types; vendoring as a property (`vendoredFile`, rung deprecated, migration script);
model identity for local models; OTel ingest; source attribution and self-citation rule.
Tracked as issues; nothing lands before the first external consumer has reviewed #0.
