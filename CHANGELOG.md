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
- Schema (issue 15): the bulk telemetry tier. `aiprov:TelemetryChain` (`prov:wasAttributedTo` the anchoring agent, `aiprov:chainHead`, `aiprov:chainLength`) and the new command `provlog bulk append|verify|anchor`: bulk records (requests, tool runs) go to a JSONL file in which every line hashes the line before it, and the graph records only the head after N records, so volume does not inflate the graph and the chain stays checkable (`verify --anchor` finds a changed, removed or reordered earlier record; records appended since are allowed). `append` reads only the last line and holds a file lock, so a write costs the same at any size; the tool adds no time and no token numbers. `validate` fails an anchor without one valid head, a length of at least 1 and an author; `report` lists anchors. Not part of this change, by the owner's decision: shards of the graph, the derived query index, and a canonical whole-graph hash. Additive; the migration step is unchanged, the vocabulary refresh adds the terms. Graphs without chains validate unchanged.
- Schema (issue 36): composite claims. `aiprov:hasPremise` (a subproperty of `prov:wasDerivedFrom`), `aiprov:composition` (`aiprov:AllOf`, `aiprov:AnyOf`, `aiprov:AtLeast` with `aiprov:minPremises`). The effective rung is computed, never written: AllOf the weakest premise, AnyOf the best, AtLeast k the k-th best, never above the own rung of the claim; a premise in state `contested` is refuted (AllOf fails with one, AnyOf with all, AtLeast k with fewer than k left). New `provlog claim --premise ID --composition all|any|atleast:N`; `claim` and `promote` refuse a rung above the effective rung. `validate` fails on a premise that is not a claim, a premise cycle and `minPremises` above the number of premises, and warns (never fails) on a composite without premises and on a claim stated above its effective rung, so a claim promoted before premises were added to it does not break (owner decision on the comment round: a warning instead of a failure). `report` lists composite claims with own and effective rung and the limiting premises. Reuse of SEPIO, the Argument Interchange Format and nanopublications is not evaluated here. Additive; the migration step is unchanged, the vocabulary refresh adds the terms. Claims without premises behave as before; a wrapper passes `--premise` and `--composition` through.
- Schema (issue 37): references across provenance graphs. A node that another repository's graph defines is marked with `rdfs:isDefinedBy` (the IRI of that graph) and carries at most `aiprov:contentHash` and `aiprov:gitCommit`, never `aiprov:filePath` or a label, and no type, so the graph that defines it can be merged later without a retype. `provlog log --used-external IRI` and `--informed-by-external IRI` with `--defined-in GRAPH_IRI` (optional `--external-hash`, `--external-commit` for exactly one reference). `validate` no longer fails a `wasInformedBy` target that is defined elsewhere and prints the number of external references; `merge` warns (exit code unchanged) about external references that the merged graphs did not resolve. Documented in `docs/attributes.md`: one base with a prefix per repository versus one base per repository, and that the hash of restricted material is itself a weak disclosure. Additive; no migration, existing graphs validate unchanged. Existing options are unchanged, so a wrapper only passes the new ones through. `validate` fails an external node that carries a file path or a label, so the privacy rule is enforced and not only followed by `log`.
- Schema (issue 16): novelty claims as a delimitation record, not a score. `aiprov:claimKind` on a claim (open vocabulary, a plain annotation, no rung), `aiprov:DelimitationRecord` (`aiprov:delimits` the claim, `aiprov:searchProtocol` to an `aiprov:SearchProtocol` with `aiprov:searchQuery`, `aiprov:searchSource`, `aiprov:searchedOn`, `aiprov:resultSetHash`; `aiprov:nearestWorks` to `aiprov:NearestWork` with `aiprov:workRef` and `aiprov:difference`; optional `aiprov:similarityHint`, exploratory and never an input to a rung). New `provlog claim --kind` and `provlog delimitation`. Two states, no scale: a novelty claim is delimitation documented when a record exists and not documented otherwise; `validate` prints the counts, `report` too. `claim --kind novelty` refuses a start at ai-confirmed or above, and `validate` fails a novelty claim at ai-confirmed or above without a record, a record that does not delimit one novelty claim or lacks its protocol or nearest works, and any numeric novelty or originality value (the schema has none; a test asserts that). Stated limitation, to carry into the documentation: a record shows that a search was made and against what; it does not show that the claim is new, and an embedding similarity is not a measure of originality. The hypothesis kind and the contradiction command are separate follow-up issues; the human check of a delimitation waits for the check records of issue 5. Additive; the migration step is unchanged, the vocabulary refresh adds the terms. Graphs without a claim kind validate unchanged; a wrapper passes `--kind` and `delimitation` through.
- Schema (issue 16): novelty claims as a delimitation record, not a score. `aiprov:claimKind` on a claim (open vocabulary, a plain annotation, no rung), `aiprov:DelimitationRecord` (`aiprov:delimits` the claim, `aiprov:searchProtocol` to an `aiprov:SearchProtocol` with `aiprov:searchQuery`, `aiprov:searchSource`, `aiprov:searchedOn`, `aiprov:resultSetHash`; `aiprov:nearestWorks` to `aiprov:NearestWork` with `aiprov:workRef` and `aiprov:difference`; optional `aiprov:similarityHint`, exploratory and never an input to a rung). New `provlog claim --kind` and `provlog delimitation`. Two states, no scale: a novelty claim is delimitation documented when a record exists and not documented otherwise; `validate` prints the counts, `report` too. `claim --kind novelty` refuses a start at ai-confirmed or above, and `validate` fails a novelty claim at ai-confirmed or above without a record, a record that does not delimit one novelty claim or lacks its protocol or nearest works, and any numeric novelty or originality value (the schema has none; a test asserts that). Stated limitation, to carry into the documentation: a record shows that a search was made and against what; it does not show that the claim is new, and an embedding similarity is not a measure of originality. The hypothesis kind and the contradiction command are separate follow-up issues; the human check of a delimitation waits for the check records of issue 5. Additive; the migration step is unchanged, the vocabulary refresh adds the terms. Graphs without a claim kind validate unchanged; a wrapper passes `--kind` and `delimitation` through. `validate` and `report` print the limitation (a delimitation record shows that a search was made, not that the claim is new) whenever a graph holds a novelty claim.
- Schema (issue 44): decision records. `aiprov:Decision` (question; `prov:wasAttributedTo` the asker; `aiprov:contentHash`; `aiprov:recommendedOption`; `aiprov:askedIn`; `aiprov:supersedes`), `aiprov:Option` (`aiprov:optionOf`), and an `aiprov:Deciding` activity (`prov:used` the decision, `prov:wasAssociatedWith` the decider, `aiprov:chosenOption`, `aiprov:decidedIn`, `aiprov:decisionState` from the scheme `aiprov:DecisionStates`: open, provisional, done). The state of a decision is that of its latest deciding activity, so nothing is edited. New `provlog decision open|decide|supersede` and `log --used-decision ID`. Question and option texts are stored as a sha256 by default and as text only with `--keep-text` and `--data-class` public, untrusted or internal, the same rule as for messages (issue 43). `done` is human-only: `decide --state done` is refused for an agent that is not a registered HumanAgent, with the same helper and wording as the human-only rungs (issue 22); an AI sets `provisional`. A changed decision is a new decision that `supersedes` the old one. `validate` fails on a malformed decision (no asker, no hash, fewer than two options, a recommendation that is no option, text that does not match its hash), an incomplete option or deciding activity, a chosen option that was not offered, `done` by a non-human, and a supersedes link to a missing decision, to itself or in a cycle; it warns on kept text in a class above internal or of unknown class. `report` counts decisions per state. `aiprov:dataClass` no longer has the domain `aiprov:Channel`. Additive; the migration step is a no-op that stamps the version and the vocabulary refresh adds the terms. Graphs without decisions validate unchanged.
- Schema (issue 23): harness identity, model variant and an unknown model with a reason. `aiprov:Harness` (a `prov:SoftwareAgent`; kind from the scheme `aiprov:HarnessKinds`: coding-agent-cli, ide-extension, portal-chat, batch; `aiprov:harnessVersion`; `aiprov:configHash` with `aiprov:configNormaliser`), `aiprov:viaHarness` on an activity, `aiprov:modelVariant` and `aiprov:modelUnknownReason` on an activity, so a model switch or variant change inside a session is recorded per response. `provlog harness --id --kind [--version] [--config-file]` hashes the normalised configuration and never stores it (normaliser `aiprov-config/1`, specified in `docs/attributes.md`: object keys sorted, list order kept because rule order decides the effective rule, values under secret-looking keys removed, URLs replaced by their sha256); kind, version and hash are write-once, a changed configuration is a new harness id. `provlog log --harness ID --model-variant V --model-unknown-reason R`. `validate` fails on `viaHarness` to a node that is not a harness and warns (never fails) on an activity via a harness with neither a model of its agent nor a stated reason; `report` lists activities, variants and unknown models per harness. `aiprov:sessionId` is described harness-neutrally. Additive; the migration step is unchanged, the vocabulary refresh adds the terms.
- Schema (issue 24): the capture path of a record. `aiprov:capturePath` (scheme `aiprov:CapturePaths`: self-report, harness-record, harness-export, gateway, script, backfill; absent means unknown, no default), `aiprov:recordedBy` and `aiprov:recordedFrom`, and `aiprov:AuxiliaryPass` for model requests outside the agent loop (compaction summary, title). `provlog log --capture-path P --recorded-by AGENT --recorded-from PATH` and `--pass auxiliary`. One telemetry witness per session: `report` counts the tokens of the capture path nearest to the request (gateway, harness-record, harness-export, script, self-report, backfill), prints what it left out, and keeps auxiliary tokens apart from the totals. `validate` warns (never fails) on a record by another agent or in arrears without `recordedFrom`, and on a session with token sums from more than one path. Readers for harness stores (`telemetry --from`) are a follow-up. Additive; the migration step is unchanged, the vocabulary refresh adds the terms.
- Schema (issue 43): conversations between agents. `aiprov:Channel` (platform, name, data class) and `aiprov:Message`
  (`prov:wasAttributedTo` the sender, `aiprov:inChannel`, `aiprov:sentAt`, `aiprov:inReplyTo`, `aiprov:refersTo`,
  `aiprov:contentHash`, optional `aiprov:content`). New `provlog message --id --channel --agent (--text | --content-hash)
  [--keep-text] [--reply-to] [--refers-to] [--sent-at] [--platform] [--channel-name] [--channel-class]`: the sha256 of the
  text is stored by default and the text itself only with `--keep-text`; `aiprov:recordedAtTime` is always written, and
  `sentAt` only when `--sent-at` is given, so a backfilled message stays distinguishable and no time is invented. `log
  --used-message ID` lets an activity use a message (`prov:used`). `validate` fails on a message without a sender, on a reply
  to a message that is not in the graph (a reply target in another graph is not supported before the cross-graph
  references of issue 37), and on a message without a content hash or whose kept text does not match it; it warns when text
  is kept in a channel above `internal` or of unknown class. `report` lists messages per channel. `aiprov:recordedAtTime`
  no longer has the domain `prov:Activity` (it now also describes a message) and the packaged vocabulary copy in
  `src/aiprov/` gained the term it had lacked. Additive; the migration step is a no-op that stamps the version and the
  vocabulary refresh adds the new terms. Graphs without messages validate unchanged.
- Schema (issue 22): an agent is an AI or a person, never both. `aiprov:HumanAgent owl:disjointWith aiprov:AIAgent`;
  `provlog agent --type human` refuses an id that is already an `AIAgent` (and `--type ai` an id that is a
  `HumanAgent`), leaving the graph file unchanged; `validate` fails a node typed as both and lists every such node.
  Repair for an existing graph: there is no automatic fix, because it is unknown which type was meant; remove the
  wrong `rdf:type` by hand. Check before upgrading with `provlog validate` (the new line "agents typed as both AI and human").
  `agent --type human` records who registered the person (`aiprov:registeredBy`, from `--by` or `$PROV_ACTOR`) and when
  (`aiprov:registeredAtTime`), write-once. New: `claim`, `source` and `promote` accept `--record-refusals`; a refused
  human-only step then writes one `aiprov:Refusal` (step, target, rung, agent, time) and nothing else. Off by default, so a
  refusal still leaves the file byte-identical for wrappers with locks and commit hooks; `validate` prints the count,
  `report` shows it and the dashboard lists the refusals. Additive; the migration step is a no-op that stamps the version.
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
