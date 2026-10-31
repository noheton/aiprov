# Changelog

## 0.1.0 — 2026-10-23
Archived on Zenodo: 10.5281/zenodo.23651334 (concept 10.5281/zenodo.23651333).
First packaged release. Content identical to the aiprov skill bundle generalised from F(AI)²R:
- `schema/aiprov-schema.ttl` — agents, activities, telemetry attributes, claims, sources,
  verification ladder (`unverified … human-read`; `source-vendored` present, see 0.2 plan).
- `provlog` CLI: init, agent, log, claim, validate, report, search, source, promote, extract.
- `aiprov-dashboard`: self-contained HTML ledger from a graph.
- Namespace `https://w3id.org/aiprov/ns#` (w3id registration pending at release time).

## 0.2.0-rc.1 — 2026-10-24
Release candidate, pinned by the thesis repository and its verification slices. Orchestration (multi-agent runs):
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

- The repository adopts its own method: `AGENTS.md` (rules for AI agents; `CLAUDE.md` imports it), a pull request
  template with an AI-assistance block, a CI job `provenance` that validates `provenance.ttl`, and a test that does the
  same locally.

## Unreleased
- Schema (#34): `aiprov:recordedAtTime` separates when a record was written from when the work happened. `log` wrote
  `prov:endedAtTime = now()` unconditionally, so a session activity carried a sub-second span where a reader
  expects the duration of the work (measured in a consuming repository: fourteen activities, 0.35–1.27 s, for
  work of hundreds of seconds). This is not only untidy: the model in force can change inside a session, so
  attribution followed the instant of logging rather than the window of the work. `log --ended` now takes the
  end of the work explicitly and defaults to now as before; `recordedAtTime` is always written, so a record
  made in arrears is distinguishable from one whose span is real — and earlier records are distinguishable by
  its absence. `validate` WARNs on a session activity whose span is under a second or missing, never fails:
  a genuinely short activity is possible and aiprov cannot tell the two apart. Additive; legacy graphs
  validate unchanged.
- Added (issue 42): `provlog migrate [--dry-run] [--to VERSION] [--agent ID]` brings a graph to the schema version of the installed provlog. Steps are chained per version, every existing triple is kept, deprecated terms are marked `owl:deprecated` and never deleted, missing vocabulary terms are added, and each run is logged as one `aiprov:Migration` activity (from, to, tool version, counts). A second run changes nothing. `init` stamps `aiprov:schemaVersion`; a graph without it is detected by its terms (0.1.0, 0.2.0) and `validate` warns (never fails). The dashboard reads graphs of every version in memory and leaves the file as it is. Fixtures of 0.1.0 and 0.2.0 in `tests/fixtures/versions/`. Additive.
- Fix (issue 21): `provlog log`, `claim`, `source` and `promote` refuse an `--agent` that was never registered with
  `provlog agent` (no `AIAgent`, `HumanAgent` or `ToolAgent` type in the graph) and name the command to register it; the
  graph file stays unchanged. `validate` fails on "agents referenced but not registered" (objects of `prov:wasAssociatedWith`
  or `prov:wasAttributedTo` without one of the three types), and `merge` therefore rejects a shard that references such an
  agent. Repair for an existing graph: one `provlog agent` call per listed id. `log` and `source` without `--agent` work as before.
- Fix (issue 18): `provlog claim --state` and `provlog source --state` now apply the human-only rule of `promote`: `human-confirmed`,
  `human-read` and the alias `lit-read` are refused unless `--agent` is a registered `HumanAgent`; before, they were accepted
  and only `validate` warned. `provlog promote` reports a node whose state is not on the ladder with a message instead of a
  traceback. Not changed: `claim` still accepts states outside the ladder (adopters record `contested`), and `validate` keeps its
  warning for graphs edited by hand.
- Found by a second review of this fix: `claim` takes a state as one token and lower-cases it, so `Human-Read` and `x/human-read`
  no longer slip past the check or become a different state in the graph; the refusal for a missing `--agent` reads clearly.
  Documented limits: the check trusts the registration (an agent can register itself as a human with `agent --type human`), and a
  human's `claim --state human-read` leaves no promotion record (use `promote`).

## 0.2.0 — planned
Session types; vendoring as a property (`vendoredFile`, rung deprecated, migration script);
model identity for local models; OTel ingest; source attribution and self-citation rule.
Tracked as issues; nothing lands before the first external consumer has reviewed #0.

## 0.2.0 — 2026-10-25
Archived on Zenodo: 10.5281/zenodo.23651340 (concept 10.5281/zenodo.23651333).
Everything of 0.2.0-rc.1, plus:
- `claim` and `source` refuse the human-only steps (`human-confirmed`, `human-read`, `lit-read`) for any agent that is
  not a registered `HumanAgent`, through the same helper as `promote`; `promote` exits with a message for a state
  outside the ladder (#18, #19). The check trusts the registration of agents (`AGENTS.md`; follow-up #22).
- Identity and logo: `docs/identity.md`; `assets/` with the salmon badge, its provenance record and the scripts that
  build the badge and the social preview (#20).
- Demo page, https://noheton.github.io/aiprov/: `site/` builds it by running `provlog` on invented data and fails if a
  command behaves differently from what the page says; `.github/workflows/pages.yml` deploys it from `main`.
- Docs: the install line pins `@v0.2.0`; `schema/README.md` names `Build` and `Repair` (#13).
- First release archived on Zenodo, together with 0.1.0 under one concept DOI.

Not in 0.2.0: the open proposals and bugs (#8 to #17, #21 to #25), planned for 0.3.0.
