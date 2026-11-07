# aiprov attribute catalogue

All properties live in `https://w3id.org/aiprov/ns#`. Attach each to the
node listed. Omit anything the provider does not report — never estimate
silently.

## On agents (aiprov:AIAgent / HumanAgent / ToolAgent)

| Property | Type | Notes / API mapping |
|---|---|---|
| foaf:name | string | display name |
| aiprov:model | string | Anthropic `model`; OpenAI `model` |
| aiprov:modelVersion | string | dated snapshot, e.g. `-20251001` |
| aiprov:provider | string | `Anthropic`, `local/llama.cpp`, gateway name |
| aiprov:endpoint | anyURI | API base URL or gateway URL |
| aiprov:contextWindow | integer | tokens |
| aiprov:knowledgeCutoff | date | from model card |
| aiprov:orcid | anyURI | humans |
| aiprov:affiliation | string | humans |

## On activities (prov:Activity subclasses)

Pass classes: `aiprov:AuthoringPass`, `aiprov:AuditPass`, `aiprov:Build`,
`aiprov:Repair`.

Timing: `prov:startedAtTime`, `prov:endedAtTime` (xsd:dateTime, with zone).

Sessions: `provlog log --session ID` makes the activity part of an `aiprov:Session` (`dcterms:isPartOf`), created on
first mention. `--session-type` (`interactive-chat`, `coding-agent`, `batch`, `evaluation`, or the IRI of your own
concept), `--session-outcome` (`succeeded`, `failed`, `interrupted`), `--session-started` and `--session-ended` are
write-once on the session; `report` groups sessions by type; `validate` fails on an activity that is part of
something that is not a session.

| Property | Type | Anthropic API | OpenAI API | llama.cpp |
|---|---|---|---|---|
| aiprov:sessionId | string | Claude Code session UUID | — | — |
| aiprov:requestId | string | response `id` | response `id` | — |
| aiprov:turnCount | integer | count of turns | idem | idem |
| aiprov:inputTokens | integer | `usage.input_tokens` | `usage.prompt_tokens` | `prompt_n` |
| aiprov:outputTokens | integer | `usage.output_tokens` | `usage.completion_tokens` | `predicted_n` |
| aiprov:cacheReadTokens | integer | `usage.cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` | — |
| aiprov:cacheWriteTokens | integer | `usage.cache_creation_input_tokens` | — | — |
| aiprov:reasoningTokens | integer | thinking tokens if reported | `completion_tokens_details.reasoning_tokens` | — |
| aiprov:totalTokens | integer | sum | `usage.total_tokens` | sum |
| aiprov:temperature | decimal | request param | request param | request param |
| aiprov:topP | decimal | request param | request param | request param |
| aiprov:maxTokens | integer | `max_tokens` | `max_completion_tokens` | `n_predict` |
| aiprov:seed | integer | — | `seed` | `seed` |
| aiprov:stopReason | string | `stop_reason` | `finish_reason` | `stop_type` |
| aiprov:cost | decimal | compute from price sheet | idem | 0 or energy-based |
| aiprov:costCurrency | string | ISO 4217 | | |
| aiprov:energyWh | decimal | optional estimate | | |
| aiprov:toolCalls | integer | count of tool_use blocks | tool_calls length | — |
| aiprov:usedTool | string, repeatable | tool names invoked | | |
| aiprov:transcript | → aiprov:Transcript | link session record | | |
| prov:used | → aiprov:Prompt / aiprov:Source | prompt files, source material | | |
| prov:wasAssociatedWith | → agent | | | |

Gateway deployments: set `aiprov:provider` to the gateway name and
`aiprov:endpoint` to the gateway URL; keep `aiprov:model` as the upstream
model ID so accounting stays comparable.

## On entities

| Property | Type | Notes |
|---|---|---|
| aiprov:contentHash | string | `sha256:<hex>` of bytes at generation |
| aiprov:promptHash | string | `sha256:<hex>` of exact prompt text |
| aiprov:gitCommit | string | commit binding entity to repo state |
| aiprov:filePath | string | repo-relative path |
| aiprov:doi | anyURI | sources |
| prov:wasGeneratedBy | → activity | mandatory for claims |
| prov:wasAttributedTo | → agent | mandatory for claims |
| aiprov:verificationState | → rung | mandatory for claims |

## Verification ladder

Rung names answer "who checked what". Position is machine-readable via
`aiprov:ladderPosition`; promotions must strictly increase it. Legacy names
(right column) are `skos:altLabel`s — all tooling normalizes them on read
and write, so fair2r graphs consolidate onto this ladder automatically.

| Pos | Rung | Meaning | Legacy aliases |
|---|---|---|---|
| 0 | unverified | Recorded; nothing checked yet by anyone | — |
| 1 | needs-research | A check was attempted/demanded and did not succeed (e.g. DOI unresolvable). Do not cite. | — |
| 2 | reference-resolved | The reference EXISTS: DOI/URL resolved in a registry, metadata captured. Says nothing about content. | retrieved, lit-retrieved |
| 3 | ai-confirmed | An AI checked the source CONTENT supports the claim. Highest rung an AI may grant. | ai-checked |
| 4 | source-vendored | A copy of the source is preserved in the repo, immune to link rot | — |
| 5 | human-confirmed | A HUMAN spot-checked that the source supports the claim. Human-only. | — |
| 6 | human-read | A HUMAN read the source in full. Top of the ladder. Human-only. | lit-read |

The offence the validator hunts is who GRANTED a rung, not who authored the
claim: an AI-authored claim may legitimately sit at human-read if a human
promoted it. Promotion activities by AI agents to rungs 5-6 are hard
failures; human-only rungs without any recorded human promotion activity
are warnings (legitimate in legacy or hand-curated graphs).

An agent is an AI or a person, never both (`aiprov:AIAgent owl:disjointWith aiprov:HumanAgent`). A person
registered with `provlog agent --type human` carries `aiprov:registeredBy` (the registering agent, from `--by`
or `$PROV_ACTOR`) and `aiprov:registeredAtTime`. With `--record-refusals`, a refused `claim`, `source` or
`promote` writes an `aiprov:Refusal` (`refusedStep`, `refusedTarget`, `refusedRung`, `refusedAgent`,
`refusedAtTime`); without the flag the graph file is not touched.

---
*AI note: drafted with AI assistance, verified against the Anthropic and
OpenAI usage-object documentation and by test-run of provlog.py; review
provider field names against current API docs before automating ingestion.*


## Orchestration (multi-agent runs)

| Term | Where | Meaning |
|---|---|---|
| `aiprov:Orchestration` | class, subclass of `prov:Activity` | Root of a multi-agent run, logged **before** any sub-agent starts |
| `aiprov:plannedAgent` | Orchestration → agent | Agent instance registered beforehand (repeatable); binds sub-activities when present |
| `aiprov:plannedBinding` | Orchestration → string | `AGENT-IRI|ROLE`: the agent may act only in its bound roles (from `--planned-agent ID:ROLE`) |
| `aiprov:plannedRole` | Orchestration → string | Planned role (repeatable); binds `aiprov:role` of sub-activities when present |
| `aiprov:role` | activity → string | Role of a sub-activity |
| `prov:wasInformedBy` | sub-activity → orchestration | Standard PROV-O link |
| `prov:actedOnBehalfOf` | agent instance → orchestrator agent | Standard PROV-O delegation |

Telemetry of sub-agents is recorded only when reported; never estimate it.

### Sharded logging of a multi-agent run

Parallel agents must not write to one graph file (the logger rewrites the whole file). Give each agent its own copy
of the graph that already contains the orchestration and its plan; the agent logs its sub-activity (`--informed-by`,
`--role`), claims and promotions there and returns the file. The dispatcher then runs
`provlog merge --from shard1.ttl shard2.ttl ...`. The plan is frozen once it is in the main graph: a shard that adds
planned agents or roles, or end times, to an existing orchestration is refused, as is a shard that adds a validation
failure.

`merge` also refuses: an unreadable shard; a shard that demotes a node below its rung in the main graph (a repair belongs
in the main graph), retypes an existing node, or adds a human-only rung without a human promotion; and it stops if the
main graph contains blank nodes. Verification states outside the ladder (for example `contested`) are kept as they are.

## Harness configuration hash (`aiprov-config/1`)

`provlog harness --config-file PATH` stores `aiprov:configHash` (sha256 of the normalised configuration) and
`aiprov:configNormaliser` (`aiprov-config/1`); the configuration itself is never stored. Two hashes compare only when the
normaliser is the same.

- JSON: object keys are sorted; arrays keep their order (the order of permission rules decides the effective rule);
  a value under a key that looks secret (token, secret, password, api key, authorization, credential, private key,
  cookie) becomes `<secret>`, so two configurations that differ only in a secret hash equal; a string that is a URL is
  replaced by `url:sha256:<hex>`; the result is serialised compactly, without ASCII escaping.
- Any other text: line by line in the original order; trailing blanks dropped; `key = value` or `key: value` with a
  secret-looking key keeps the key and `<secret>` as value; URLs are replaced as above.

## Bulk telemetry tier (`provlog bulk`)

Decisions (claims, rungs, agents, sessions) stay in the graph. Volume that would inflate it, one record per request or
tool run, goes to a JSONL file in which every line carries the hash of the line before it:

    {"data":{...},"hash":"sha256:...","prev":"sha256:...","seq":1}

`hash` is the sha256 of `prev`, `seq` and the canonical `data` (sorted keys, no blanks), joined by newlines; the first
`prev` is `sha256:` followed by 64 zeros. `bulk append --file F --data JSON` adds one line under a file lock and reads
only the last line, so the cost of a write does not depend on the size of the file. Nothing is added by the tool: no
time, no token count; the caller puts into `data` what the harness or gateway reported, and nothing it estimated.
`bulk verify --file F` walks the whole chain and names the first bad line. `bulk anchor --id ID --file F --agent A`
writes one `aiprov:TelemetryChain` into the graph with `aiprov:chainHead` and `aiprov:chainLength` (`--upto N` anchors
the first N records); the graph never holds a record. `bulk verify --file F --anchor ID` checks that the first
`chainLength` records still hash to the recorded head, so records added since are fine and a changed, removed or
reordered earlier record is found. `validate` fails an anchor without one valid head, a length of at least 1 and an
author; `report` lists the anchors.

Limits: the chain shows that the file was not changed after the anchor, not that the records are true, and not that
nothing was appended before the next anchor. Whoever can rewrite the file and the graph together can forge both; for
tamper evidence the graph commit has to be signed or published. Keep secrets and personal data out of `data`: the file
is not covered by the graph rules. Shards of the graph itself and a derived query index are not part of this change.

## References across provenance graphs

A project split into several repositories keeps one `provenance.ttl` per repository. Work often crosses the border: a
gate run in one repository used a commit of another, a fix was informed by a run elsewhere. Copying the foreign node
would leak what the split protects, so a graph refers to it instead.

- `provlog log --used-external IRI --defined-in GRAPH_IRI` (prov:used) and `--informed-by-external IRI --defined-in GRAPH_IRI`
  (prov:wasInformedBy). Both are repeatable. The node gets `rdfs:isDefinedBy GRAPH_IRI` and nothing else, except what you
  add: `--external-hash sha256:<hex>` and `--external-commit SHA`, allowed when the call names exactly one external
  reference. There is no path and no label for a foreign node, by design, and no `rdf:type`: the graph that defines the node
  types it, so merging the two graphs later does not count as a retype.
- `validate` accepts a `wasInformedBy` target that is defined elsewhere and prints `external references: N` (nodes marked
  `rdfs:isDefinedBy` and not defined in this graph).
- `merge` prints a WARN, with unchanged exit code, for external references that the merged graphs still do not define.

Two layouts work. **One base per repository**: each graph has its own base; an external IRI is minted by the other
repository and is unrelated to this base. **One base with a prefix per repository** (for example `.../prov/`,
`.../prov/data/`, `.../prov/ci/`): the IRIs of all graphs live in one space, which makes the references easy to read and
to resolve after a merge. For repositories meant to be joined, use the shared base with prefixes; otherwise keep one base
each.

**Disclosure.** A bare content hash of a small or guessable file can be confirmed by anyone who can guess the content, so
the hash of restricted material is itself a weak disclosure. `--external-hash` is optional; whether to publish it is for the
owner of the restricted graph to decide.
