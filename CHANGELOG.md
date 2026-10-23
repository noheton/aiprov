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

- `provlog merge --from SHARD...` for sharded logging: each agent of a run writes into its own copy of the graph
  (parallel writers to one file overwrite each other); the dispatcher unions the shards, append-only. A shard is
  refused if it edits the plan or timing of an orchestration already in the main graph, contains blank nodes, or
  introduces any new `validate` failure; accepted shards are still merged. Verification states are normalised to the
  highest rung, because `promote` in a second shard leaves the older state behind in the union. `--dry-run` writes nothing.

- Hardening of `merge` and the plan after a second multi-agent review (nine agents that logged themselves into
  shards; 8 findings reported, 6 verified, 3 confirmed, 3 refuted): the regression check now compares the offending
  nodes, not only the failure counts (fixing one failure while adding another is refused); a human-only rung in a
  shard without a human promotion is refused; a shard that demotes a node, retypes an existing node, or is unreadable
  is refused with a reason instead of crashing; states outside the ladder (`contested`) are kept; a main graph with
  blank nodes is named as the cause; shard order does not matter.
- Plan bindings: `provlog log --orchestration --planned-agent ID:ROLE` ties an agent to one role
  (`aiprov:plannedBinding`); before, any planned agent could act in any planned role.

## 0.2.0 — planned
Session types; vendoring as a property (`vendoredFile`, rung deprecated, migration script);
model identity for local models; OTel ingest; source attribution and self-citation rule.
Tracked as issues; nothing lands before the first external consumer has reviewed #0.
