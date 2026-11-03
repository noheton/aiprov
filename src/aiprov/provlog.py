#!/usr/bin/env python3
"""provlog — append-only AI provenance logger over PROV-O (aiprov: profile).

Commands:
  init                       Seed provenance.ttl from the aiprov schema.
  agent   --id --type ...    Register a human/AI/tool agent with attributes.
  log     --activity ...     Record an activity with full inference telemetry
                             (tokens, cost, model, session, tools, prompt hash)
                             and optionally the entities it generated/used.
  claim   --id ...           Add a claim bound to a parent activity + agent.
  (cross-graph) log --used-external IRI | --informed-by-external IRI --defined-in GRAPH_IRI: reference a node
                             that another repository's graph defines, without copying it.
  merge   --from SHARD...    Union per-agent shard graphs into the main graph; refuses shards that
                             edit a frozen plan or add validation failures.
  (multi-agent) log --orchestration --planned-role/--planned-agent, then sub-activities with
                             --informed-by/--role; agent --acted-on-behalf-of.
  message --id --channel --agent (--text | --content-hash) ...   Record one message of an agent in a channel
                             (hash by default; the text only with --keep-text).
  decision open|decide|supersede --id ...   Record a decision: question, options, recommendation, who chose what
                             (hash by default; `done` only by a registered human; log --used-decision links work to it).
  bulk append|verify|anchor --file F ...   Bulk telemetry tier: a hash-chained JSONL file; the graph keeps only its head.
  harness --id --kind ... [--version V] [--config-file PATH]   Register the harness (coding-agent CLI, IDE extension,
                             portal chat, batch) an activity ran under; the configuration is hashed, never stored.
  validate                   Conformance: parentless claims, AI-granted
                             human-only verification rungs, missing attribution.
  report                     Totals: tokens, cost, activities per agent, rungs.
  migrate [--dry-run] [--to V]  Bring the graph to the schema version of this provlog: chained steps, every
                             existing triple kept, deprecated terms marked, one aiprov:Migration activity per run.
  search                     Self-contained literature search over open APIs
                             (Crossref, OpenAlex, arXiv, DataCite) — no MCP
                             server, no key, no paid service required.
  source                     Register a literature source; --verify checks the
                             DOI against Crossref/OpenAlex (open APIs, no key)
                             and promotes unverified -> retrieved with metadata.
  promote                    Move a source or claim up the verification ladder.
                             Ladder order is enforced; human-only rungs
                             (human-confirmed, human-read) require --agent of a
                             registered HumanAgent. Every promotion is logged as
                             an AuditPass activity.
  extract                    Backward-closure subgraph of everything that
                             contributed to chosen seed entity types; can
                             also render a dashboard of the extract.

All writes are appends; the graph is the audit substrate. AI note: this tool
was drafted with AI assistance and verified by test-run; review before
production use.
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, os, pathlib, re, sys
try:
    import fcntl
except ImportError:  # not available on Windows: appends then run without the file lock
    fcntl = None
from rdflib import Graph, Namespace, Literal, URIRef, RDF, RDFS, XSD, OWL

AIPROV = Namespace("https://w3id.org/aiprov/ns#")
FAIR2R = Namespace("https://noheton.org/f-ai-r/ns#")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCT = Namespace("http://purl.org/dc/terms/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")

DEFAULT_BASE = "https://example.org/prov/"
GRAPH = pathlib.Path("provenance.ttl")
SCHEMA = pathlib.Path(__file__).resolve().parent / "aiprov-schema.ttl"


def ns(base: str, kind: str) -> Namespace:
    return Namespace(f"{base}{kind}/")


def load() -> Graph:
    g = Graph()
    if GRAPH.exists():
        g.parse(GRAPH, format="turtle")
    for p, u in [("aiprov", AIPROV), ("prov", PROV), ("dcterms", DCT), ("foaf", FOAF),
             ("rdfs", RDFS)]:
        g.bind(p, u)
    return g


def save(g: Graph) -> None:
    g.serialize(GRAPH, format="turtle")


def now() -> Literal:
    return Literal(datetime.datetime.now().astimezone().isoformat(), datatype=XSD.dateTime)


def cmd_init(a) -> None:
    if GRAPH.exists() and not a.force:
        sys.exit("provenance.ttl exists; use --force to reseed")
    text = SCHEMA.read_text(encoding="utf-8").replace("https://example.org/prov/", a.base)
    GRAPH.write_text(text, encoding="utf-8")
    g = load()  # parse check
    stamp_version(g, a.base, SCHEMA_VERSION)
    save(g)
    print(f"Seeded {GRAPH} ({len(g)} triples, base {a.base}, schema {SCHEMA_VERSION})")


def cmd_agent(a) -> None:
    g = load()
    s = ns(a.base, "agent")[a.id]
    cls = {"ai": AIPROV.AIAgent, "human": AIPROV.HumanAgent, "tool": AIPROV.ToolAgent}[a.type]
    # An agent is an AI or a person, never both (issue 22): a self-registration as a person would otherwise
    # turn a model into an agent that may grant the human-only rungs.
    if a.type == "human" and (s, RDF.type, AIPROV.AIAgent) in g:
        sys.exit(f"REFUSED: agent:{a.id} is registered as an AI agent and cannot also be a person; "
                 f"register the person under their own id")
    if a.type == "ai" and (s, RDF.type, AIPROV.HumanAgent) in g:
        sys.exit(f"REFUSED: agent:{a.id} is registered as a person and cannot also be an AI agent")
    newly_human = a.type == "human" and (s, RDF.type, AIPROV.HumanAgent) not in g
    g.add((s, RDF.type, cls))
    if newly_human:  # write-once: a repeated registration keeps the first trace
        by = getattr(a, "by", None) or os.environ.get("PROV_ACTOR")
        if by:
            g.add((s, AIPROV.registeredBy, ns(a.base, "agent")[by]))
        g.add((s, AIPROV.registeredAtTime, now()))
    if a.name:
        g.add((s, FOAF.name, Literal(a.name)))
    for key, prop, dt in [
        ("model", AIPROV.model, XSD.string), ("model_version", AIPROV.modelVersion, XSD.string),
        ("provider", AIPROV.provider, XSD.string), ("endpoint", AIPROV.endpoint, XSD.anyURI),
        ("context_window", AIPROV.contextWindow, XSD.integer),
        ("knowledge_cutoff", AIPROV.knowledgeCutoff, XSD.date),
        ("orcid", AIPROV.orcid, XSD.anyURI), ("affiliation", AIPROV.affiliation, XSD.string),
    ]:
        v = getattr(a, key, None)
        if v is not None:
            g.add((s, prop, Literal(v, datatype=dt)))
    if getattr(a, "acted_on_behalf_of", None):
        g.add((s, PROV.actedOnBehalfOf, ns(a.base, "agent")[a.acted_on_behalf_of]))
    save(g)
    print(f"agent:{a.id} registered ({a.type})")


HARNESS_KINDS = ["coding-agent-cli", "ide-extension", "portal-chat", "batch"]
CONFIG_NORMALISER = "aiprov-config/1"  # name and version of the normaliser; recorded next to every config hash
_SECRET_KEY = re.compile(r"(token(?!s)|secret|passw|api[-_]?key|authorization|credential|private[-_]?key|cookie)", re.I)
_URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.I)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm_config(value, key: str = ""):
    """aiprov-config/1: object keys sorted; lists keep their order (the order of permission rules decides the
    effective rule); a value under a secret-looking key becomes <secret>; a URL is replaced by its sha256."""
    if key and _SECRET_KEY.search(key) and value is not None:
        return "<secret>"
    if isinstance(value, dict):
        return {k: _norm_config(v, k) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_norm_config(v, key) for v in value]
    if isinstance(value, str) and _URL.fullmatch(value.strip()):
        return "url:sha256:" + _sha(value.strip())
    return value


def config_hash(text: str) -> str:
    """sha256 of the normalised configuration (aiprov-config/1). JSON is normalised structurally; any other text
    line by line (trailing blanks dropped, `key = value` or `key: value` with a secret-looking key redacted,
    URLs hashed), in the original line order."""
    import json
    try:
        canon = json.dumps(_norm_config(json.loads(text)), ensure_ascii=False, separators=(",", ":"))
    except ValueError:
        lines = []
        for ln in text.splitlines():
            ln = ln.rstrip()
            m = re.match(r"^(\s*)([^=:#]+?)\s*([=:])\s*(.*)$", ln)
            if m and _SECRET_KEY.search(m.group(2)):
                ln = f"{m.group(1)}{m.group(2)}{m.group(3)}<secret>"
            lines.append(_URL.sub(lambda u: "url:sha256:" + _sha(u.group(0)), ln))
        canon = "\n".join(lines)
    return "sha256:" + _sha(canon)


def cmd_harness(a) -> None:
    """Register a harness (issue 23). Kind, version and configuration hash are write-once: a changed
    configuration is a new harness id, so the record of an earlier activity keeps what it ran under."""
    g = load()
    node = ns(a.base, "harness")[a.id]
    if (node, RDF.type, None) in g and (node, RDF.type, AIPROV.Harness) not in g:
        sys.exit(f"{node} exists and is not a harness")
    if a.kind in HARNESS_KINDS:
        kind = AIPROV["harnessKind-" + a.kind]
    elif a.kind.startswith("http://") or a.kind.startswith("https://"):
        kind = URIRef(a.kind)
    else:
        sys.exit(f"--kind: {a.kind} is not one of {', '.join(HARNESS_KINDS)} or the IRI of your own concept")
    values = [(AIPROV.harnessKind, kind, "--kind")]
    if a.version is not None:
        values.append((AIPROV.harnessVersion, Literal(a.version), "--version"))
    if a.config_file:
        cp = pathlib.Path(a.config_file)
        if not cp.is_file():
            sys.exit(f"--config-file: {a.config_file} is not a file")
        values.append((AIPROV.configHash, Literal(config_hash(cp.read_text(encoding="utf-8"))), "--config-file"))
        values.append((AIPROV.configNormaliser, Literal(CONFIG_NORMALISER), "--config-file"))
    for prop, val, flag in values:
        old = set(g.objects(node, prop))
        if old and val not in old:
            sys.exit(f"{flag}: harness {a.id} already has {', '.join(str(o) for o in old)}; the graph is append-only, "
                     "register the changed harness under a new id")
    g.add((node, RDF.type, AIPROV.Harness))
    for prop, val, _ in values:
        g.add((node, prop, val))
    if a.name:
        g.add((node, FOAF.name, Literal(a.name)))
    save(g)
    print(f"harness:{a.id} registered ({a.kind})")


def _link_harness(g: Graph, a, act) -> None:
    """The harness an activity ran under, the reasoning variant in force and, for an unknown model, the reason (issue 23)."""
    if a.harness:
        h = ns(a.base, "harness")[a.harness]
        if (h, RDF.type, AIPROV.Harness) not in g:
            sys.exit(f"--harness: harness {a.harness} is not registered; register it with `provlog harness` first")
        g.add((act, AIPROV.viaHarness, h))
    if a.model_variant:
        g.add((act, AIPROV.modelVariant, Literal(a.model_variant)))
    if a.model_unknown_reason:
        g.add((act, AIPROV.modelUnknownReason, Literal(a.model_unknown_reason)))


def plan_violation(g: Graph, base: str, parent, agent, role) -> "str | None":
    """Why a sub-activity of an orchestration breaks the plan, or None. Only declared lists bind."""
    agents = set(g.objects(parent, AIPROV.plannedAgent))
    roles = {str(r) for r in g.objects(parent, AIPROV.plannedRole)}
    if agents and agent is None:
        return "the orchestration declares planned agents, so --agent is required"
    if agents and ns(base, "agent")[agent] not in agents:
        return f"agent {agent} is not among the planned agents of the orchestration"
    if roles and role is None:
        return "the orchestration declares planned roles, so --role is required"
    if roles and role not in roles:
        return f"role {role} is not among the planned roles of the orchestration"
    if agent is not None and role is not None:
        pref = str(ns(base, "agent")[agent]) + "|"
        bound = sorted(str(b)[len(pref):] for b in g.objects(parent, AIPROV.plannedBinding) if str(b).startswith(pref))
        if bound and role not in bound:
            return f"agent {agent} is bound to role(s) {', '.join(bound)}, not {role}"
    return None


FALLBACK_REASONS = ["error", "timeout", "policy", "capacity"]


def _link_models(g: Graph, a, act) -> None:
    """Several models behind one answer: role, fallback, routing rule, judge and score (issue 9)."""
    if a.fallback_reason and not a.fallback_of:
        sys.exit("--fallback-reason needs --fallback-of")
    if bool(a.judges) != (a.score is not None):
        sys.exit("--judges and --score belong together: a judge activity used an answer and generated a score")
    if a.model_role:
        g.add((act, AIPROV.modelRole, Literal(a.model_role)))
    if a.fallback_of:
        target = ns(a.base, "activity")[a.fallback_of]
        if target == act:
            sys.exit("--fallback-of: an activity cannot be the fallback of itself")
        if (target, PROV.endedAtTime, None) not in g:
            sys.exit(f"--fallback-of: activity {a.fallback_of} is not logged")
        g.add((act, AIPROV.fallbackOf, target))
        if a.fallback_reason:
            g.add((act, AIPROV.fallbackReason, Literal(a.fallback_reason)))
    if a.routed_by:
        plan = ns(a.base, "entity")["plan-" + a.routed_by]
        g.add((plan, RDF.type, PROV.Plan))
        g.add((act, AIPROV.routedBy, plan))
    if a.judges:
        try:
            float(a.score)
        except ValueError:
            sys.exit(f"--score: {a.score} is not a number")
        answer = ns(a.base, "entity")[pathlib.Path(a.judges).name.replace(".", "-")]
        if (answer, PROV.wasGeneratedBy, None) not in g:
            sys.exit(f"--judges: {a.judges} is not the output of a logged activity; log the answer first")
        score = ns(a.base, "entity")["score-" + a.activity]
        g.add((score, RDF.type, AIPROV.Score))
        g.add((score, AIPROV.scoreValue, Literal(a.score, datatype=XSD.decimal)))
        g.add((score, PROV.wasGeneratedBy, act))
        if a.agent:
            g.add((score, PROV.wasAttributedTo, ns(a.base, "agent")[a.agent]))
        g.add((act, PROV.used, answer))
SESSION_TYPES = ["interactive-chat", "coding-agent", "batch", "evaluation"]
SESSION_OUTCOMES = ["succeeded", "failed", "interrupted"]


def _session_type_node(value: str) -> URIRef:
    """A built-in type name, or the full IRI of a concept in the adopter's own scheme."""
    if value.startswith(("http://", "https://")):
        return URIRef(value)
    if value not in SESSION_TYPES:
        sys.exit(f"--session-type: {value} is not one of {', '.join(SESSION_TYPES)}; "
                 "use the IRI of your own concept for another kind")
    return AIPROV["sessionType-" + value]


def _session_time(value: str, flag: str) -> Literal:
    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(f"{flag}: {value} is not an ISO 8601 date-time")
    return Literal(value, datatype=XSD.dateTime)


def _link_session(g: Graph, a, act) -> None:
    """Create the session on first mention and attach the activity to it. Type, start, end and outcome are
    write-once: a value may be added while absent, a different second value is refused (append-only)."""
    given = {"--session-type": a.session_type, "--session-outcome": a.session_outcome,
             "--session-started": a.session_started, "--session-ended": a.session_ended}
    if not a.session:
        if any(v is not None for v in given.values()):
            sys.exit(", ".join(k for k, v in given.items() if v is not None) + " need --session")
        return
    node = ns(a.base, "session")[a.session]
    if (node, RDF.type, None) in g and (node, RDF.type, AIPROV.Session) not in g:
        sys.exit(f"{node} exists and is not a session")
    values = []
    if a.session_type is not None:
        values.append((AIPROV.sessionType, _session_type_node(a.session_type), "--session-type"))
    if a.session_outcome is not None:
        values.append((AIPROV.sessionOutcome, Literal(a.session_outcome), "--session-outcome"))
    if a.session_started is not None:
        values.append((PROV.startedAtTime, _session_time(a.session_started, "--session-started"), "--session-started"))
    if a.session_ended is not None:
        values.append((PROV.endedAtTime, _session_time(a.session_ended, "--session-ended"), "--session-ended"))
    for prop, val, flag in values:
        old = set(g.objects(node, prop))
        if old and val not in old:
            sys.exit(f"{flag}: session {a.session} already has {', '.join(str(o) for o in old)}; "
                     "the graph is append-only, a recorded value is not replaced")
    g.add((node, RDF.type, AIPROV.Session))
    g.add((node, AIPROV.sessionId, Literal(a.session)))
    for prop, val, _ in values:
        g.add((node, prop, val))
    start = next(iter(g.objects(node, PROV.startedAtTime)), None)
    end = next(iter(g.objects(node, PROV.endedAtTime)), None)
    if start is not None and end is not None:
        try:
            late = (datetime.datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                    < datetime.datetime.fromisoformat(str(start).replace("Z", "+00:00")))
        except TypeError:  # one with and one without a time zone: cannot be compared
            late = False
        if late:
            sys.exit(f"session {a.session} would end before it started")
    g.add((act, DCT.isPartOf, node))


# How a record came to be (issue 24). The order is the precedence when two paths report the same session: the
# one nearest to the request wins, the others are not added up.
CAPTURE_PATHS = ["gateway", "harness-record", "harness-export", "script", "self-report", "backfill"]


def _capture_path(g: Graph, act) -> "str | None":
    v = next(iter(g.objects(act, AIPROV.capturePath)), None)
    return None if v is None else str(v).removeprefix(str(AIPROV) + "capturePath-")


def _act_tokens(g: Graph, act) -> int:
    t = next(iter(g.objects(act, AIPROV.totalTokens)), None)
    if t is not None:
        return int(t)
    return sum(int(o) for p in (AIPROV.inputTokens, AIPROV.outputTokens) for o in g.objects(act, p))


def _witness_split(g: Graph) -> "tuple[set, set, list]":
    """(auxiliary passes, activities not counted because another capture path already reports their session,
    sessions with two paths). One telemetry witness per session; an activity without a path is kept, since it
    cannot be shown to repeat another."""
    aux = set(g.subjects(RDF.type, AIPROV.AuxiliaryPass))
    token_acts = {x for p in (AIPROV.inputTokens, AIPROV.outputTokens, AIPROV.totalTokens) for x in g.subjects(p, None)}
    by_session: dict = {}
    for act in token_acts - aux:
        for sess in g.objects(act, DCT.isPartOf):
            by_session.setdefault(sess, []).append(act)
    dropped: set = set()
    conflicts: list = []
    for sess, acts in by_session.items():
        paths = {pp for pp in (_capture_path(g, x) for x in acts) if pp}
        if len(paths) > 1:
            conflicts.append((sess,))
            best = min(paths, key=lambda pp: CAPTURE_PATHS.index(pp) if pp in CAPTURE_PATHS else 99)
            dropped |= {x for x in acts if _capture_path(g, x) not in (None, best)}
    return aux, dropped, conflicts


ACT_ATTRS = [  # (cli key, property, xsd type)
    ("session_id", AIPROV.sessionId, XSD.string), ("request_id", AIPROV.requestId, XSD.string),
    ("turns", AIPROV.turnCount, XSD.integer),
    ("input_tokens", AIPROV.inputTokens, XSD.integer), ("output_tokens", AIPROV.outputTokens, XSD.integer),
    ("cache_read_tokens", AIPROV.cacheReadTokens, XSD.integer),
    ("cache_write_tokens", AIPROV.cacheWriteTokens, XSD.integer),
    ("reasoning_tokens", AIPROV.reasoningTokens, XSD.integer),
    ("temperature", AIPROV.temperature, XSD.decimal), ("top_p", AIPROV.topP, XSD.decimal),
    ("max_tokens", AIPROV.maxTokens, XSD.integer), ("seed", AIPROV.seed, XSD.integer),
    ("stop_reason", AIPROV.stopReason, XSD.string),
    ("cost", AIPROV.cost, XSD.decimal), ("currency", AIPROV.costCurrency, XSD.string),
    ("energy_wh", AIPROV.energyWh, XSD.decimal), ("tool_calls", AIPROV.toolCalls, XSD.integer),
]


SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


def _external_node(g: Graph, iri: str, defined_in: str, hash_: str | None, commit: str | None) -> URIRef:
    """A node that another provenance graph defines (issue 37). Only rdfs:isDefinedBy, optionally the content
    hash and the commit are written: never a path or a label, so a restricted node is not leaked into a less
    restricted graph. The node stays untyped; the graph that defines it types it, so a merge does not retype it."""
    if not defined_in or not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$", defined_in):
        sys.exit("--defined-in must be the IRI of the graph that defines the referenced node")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$", iri):
        sys.exit(f"external reference {iri!r} is not an absolute IRI")
    node = URIRef(iri)
    if (node, RDF.type, None) in g and (node, RDFS.isDefinedBy, None) not in g:
        sys.exit(f"{iri} is defined in this graph; it is not an external reference")
    if hash_ and not SHA256_REF.match(hash_):
        sys.exit("--external-hash must be sha256:<64 hex digits>")
    for prop, val, opt in ((AIPROV.contentHash, hash_, "--external-hash"), (AIPROV.gitCommit, commit, "--external-commit")):
        old = [str(o) for o in g.objects(node, prop)]
        if val and old and val not in old:
            sys.exit(f"{opt}: {iri} already carries a different value; the graph is append-only")
    g.add((node, RDFS.isDefinedBy, URIRef(defined_in)))
    if hash_:
        g.add((node, AIPROV.contentHash, Literal(hash_)))
    if commit:
        g.add((node, AIPROV.gitCommit, Literal(commit)))
    return node


def _external_refs(g: Graph) -> list:
    """Nodes that point to another graph with rdfs:isDefinedBy and are not defined here (no type)."""
    return sorted(n for n in set(g.subjects(RDFS.isDefinedBy, None)) if (n, RDF.type, None) not in g)


def cmd_log(a) -> None:
    g = load()
    act = ns(a.base, "activity")[a.activity]
    cls = {"authoring": AIPROV.AuthoringPass, "audit": AIPROV.AuditPass,
           "build": AIPROV.Build, "repair": AIPROV.Repair,
           "auxiliary": AIPROV.AuxiliaryPass}.get(a.pass_, PROV.Activity)
    if a.informed_by == a.activity:
        sys.exit("--informed-by: an activity cannot be informed by itself")
    if (a.orchestration or a.informed_by or (act, RDF.type, AIPROV.Orchestration) in g) \
            and (act, PROV.endedAtTime, None) in g:
        sys.exit(f"activity {a.activity} is already logged; the graph is append-only, use a new id")
    if a.orchestration:
        cls = AIPROV.Orchestration
    elif a.planned_role or a.planned_agent:
        sys.exit("--planned-role/--planned-agent need --orchestration")
    for pa in a.planned_agent or []:
        if (ns(a.base, "agent")[pa.partition(":")[0]], RDF.type, None) not in g:
            sys.exit(f"planned agent {pa.partition(':')[0]} is not registered; register agents before the orchestration")
    if a.informed_by:
        parent = ns(a.base, "activity")[a.informed_by]
        if (parent, PROV.endedAtTime, None) not in g:
            sys.exit(f"--informed-by: activity {a.informed_by} is not logged")
        why = plan_violation(g, a.base, parent, a.agent, a.role) if (parent, RDF.type, AIPROV.Orchestration) in g else None
        if why:
            sys.exit("refused: " + why)
        g.add((act, PROV.wasInformedBy, parent))
    _require_registered(g, a.base, a.agent)
    for r in a.planned_role or []:
        g.add((act, AIPROV.plannedRole, Literal(r)))
    for pa in a.planned_agent or []:
        aid, _, bound = pa.partition(":")  # ID or ID:ROLE (the agent may act only in that role)
        g.add((act, AIPROV.plannedAgent, ns(a.base, "agent")[aid]))
        if bound:
            g.add((act, AIPROV.plannedRole, Literal(bound)))
            g.add((act, AIPROV.plannedBinding, Literal(f"{ns(a.base, 'agent')[aid]}|{bound}")))
    if a.role:
        g.add((act, AIPROV.role, Literal(a.role)))
    g.add((act, RDF.type, cls))
    _link_models(g, a, act)
    _link_harness(g, a, act)
    _link_session(g, a, act)
    if a.recorded_by:
        _require_registered(g, a.base, a.recorded_by)
    if a.capture_path:
        g.add((act, AIPROV.capturePath, AIPROV["capturePath-" + a.capture_path]))
    if a.recorded_by:
        g.add((act, AIPROV.recordedBy, ns(a.base, "agent")[a.recorded_by]))
    if a.recorded_from:
        rf = ns(a.base, "entity")[pathlib.Path(a.recorded_from).name.replace(".", "-")]
        g.add((rf, RDF.type, AIPROV.Artefact))
        g.add((rf, AIPROV.filePath, Literal(a.recorded_from)))
        rp = pathlib.Path(a.recorded_from)
        if rp.exists():
            g.add((rf, AIPROV.contentHash, Literal("sha256:" + hashlib.sha256(rp.read_bytes()).hexdigest())))
        g.add((act, AIPROV.recordedFrom, rf))
    if a.label:
        g.add((act, RDFS.label, Literal(a.label, lang="en")))
    g.add((act, PROV.endedAtTime, Literal(a.ended, datatype=XSD.dateTime) if a.ended else now()))
    if a.started:
        g.add((act, PROV.startedAtTime, Literal(a.started, datatype=XSD.dateTime)))
    # The moment of bookkeeping, kept apart from the span of the work: without it a record written in arrears
    # cannot be told apart from one whose work really took the length it claims.
    g.add((act, AIPROV.recordedAtTime, now()))
    if a.agent:
        g.add((act, PROV.wasAssociatedWith, ns(a.base, "agent")[a.agent]))
    for key, prop, dt in ACT_ATTRS:
        v = getattr(a, key, None)
        if v is not None:
            g.add((act, prop, Literal(v, datatype=dt)))
    it = int(a.input_tokens or 0) + int(a.output_tokens or 0)
    if a.total_tokens is not None:
        g.add((act, AIPROV.totalTokens, Literal(a.total_tokens, datatype=XSD.integer)))
    elif it:
        g.add((act, AIPROV.totalTokens, Literal(it, datatype=XSD.integer)))
    for t in a.tool or []:
        g.add((act, AIPROV.usedTool, Literal(t)))
    if a.prompt_file:
        p = pathlib.Path(a.prompt_file)
        pe = ns(a.base, "entity")["prompt-" + p.stem]
        g.add((pe, RDF.type, AIPROV.Prompt))
        g.add((pe, DCT.source, URIRef(p.as_posix())))
        if p.exists():
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            g.add((pe, AIPROV.promptHash, Literal("sha256:" + h)))
        g.add((act, PROV.used, pe))
    if a.transcript:
        te = ns(a.base, "entity")["transcript-" + pathlib.Path(a.transcript).stem]
        g.add((te, RDF.type, AIPROV.Transcript))
        g.add((te, DCT.source, URIRef(a.transcript)))
        g.add((act, AIPROV.transcript, te))
    for path in a.generated or []:
        e = ns(a.base, "entity")[pathlib.Path(path).name.replace(".", "-")]
        g.add((e, RDF.type, AIPROV.Artefact))
        g.add((e, AIPROV.filePath, Literal(path)))
        fp = pathlib.Path(path)
        if fp.exists():
            g.add((e, AIPROV.contentHash,
                   Literal("sha256:" + hashlib.sha256(fp.read_bytes()).hexdigest())))
        g.add((e, PROV.wasGeneratedBy, act))
        if a.agent:
            g.add((e, PROV.wasAttributedTo, ns(a.base, "agent")[a.agent]))
        if a.commit:
            g.add((e, AIPROV.gitCommit, Literal(a.commit)))
    for mid in a.used_message or []:
        m_ = ns(a.base, "message")[mid]
        if (m_, RDF.type, AIPROV.Message) not in g:
            sys.exit(f"--used-message: message {mid} is not logged; log it with `provlog message` first")
        g.add((act, PROV.used, m_))
    for did in a.used_decision or []:
        d_ = ns(a.base, "decision")[did]
        if not _is_decision(g, d_):
            sys.exit(f"--used-decision: decision {did} is not logged; open it with `provlog decision open` first")
        g.add((act, PROV.used, d_))
    for path in a.used or []:
        e = ns(a.base, "source")[pathlib.Path(path).name.replace(".", "-")]
        g.add((e, RDF.type, AIPROV.Source))
        g.add((e, AIPROV.filePath, Literal(path)))
        g.add((act, PROV.used, e))
    ext_used, ext_informed = a.used_external or [], a.informed_by_external or []
    if (a.defined_in or a.external_hash or a.external_commit) and not (ext_used or ext_informed):
        sys.exit("--defined-in, --external-hash and --external-commit belong to --used-external or --informed-by-external")
    if ext_used or ext_informed:
        if (a.external_hash or a.external_commit) and len(ext_used) + len(ext_informed) != 1:
            sys.exit("--external-hash and --external-commit describe one node: give exactly one external reference")
        for iri in ext_used:
            g.add((act, PROV.used, _external_node(g, iri, a.defined_in, a.external_hash, a.external_commit)))
        for iri in ext_informed:
            if iri == str(act):
                sys.exit("--informed-by-external: an activity cannot be informed by itself")
            g.add((act, PROV.wasInformedBy, _external_node(g, iri, a.defined_in, a.external_hash, a.external_commit)))
    save(g)
    print(f"act:{a.activity} logged ({len(g)} triples total)")


AGENT_CLASSES = (AIPROV.AIAgent, AIPROV.HumanAgent, AIPROV.ToolAgent)


def _is_registered(g: Graph, base: str, agent: str) -> bool:
    node = ns(base, "agent")[agent]
    return any((node, RDF.type, c) in g for c in AGENT_CLASSES)


def _require_registered(g: Graph, base: str, agent: "str | None") -> None:
    """Exit when --agent names an id that `provlog agent` never registered (issue 21): an untyped agent is
    neither AI nor human nor tool, so reports cannot count it and the human-only rule cannot judge it."""
    if agent is not None and not _is_registered(g, base, agent):
        sys.exit(f"REFUSED: agent:{agent} is not registered; register it first with "
                 f"`provlog agent --id {agent} --type ai|human|tool ...`")


def _is_human(g: Graph, base: str, agent: "str | None") -> bool:
    return agent is not None and (ns(base, "agent")[agent], RDF.type, AIPROV.HumanAgent) in g


def _record_refusal(base: str, agent: "str | None", step: str, target: str, rung: str) -> None:
    """Write one aiprov:Refusal and nothing else (issue 22). The graph is read afresh: the caller's copy may hold
    nodes it began to build before the refusal, and those must not reach the file."""
    g = load()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    node = ns(base, "refusal")[f"{step}-{target}-{stamp}"]
    g.add((node, RDF.type, AIPROV.Refusal))
    g.add((node, RDFS.label, Literal(f"Refused {step} of {target} at rung {rung}", lang="en")))
    g.add((node, AIPROV.refusedStep, Literal(step)))
    g.add((node, AIPROV.refusedTarget, Literal(target)))
    g.add((node, AIPROV.refusedRung, Literal(rung)))
    if agent:
        g.add((node, AIPROV.refusedAgent, ns(base, "agent")[agent]))
    g.add((node, AIPROV.refusedAtTime, now()))
    save(g)


def _not_human_reason(agent: "str | None") -> str:
    """Why an agent may not take a human-only step; one wording for rungs (issue 22) and decisions (issue 44)."""
    return (f"agent:{agent} is not a registered HumanAgent" if agent
            else "no --agent was given, and a registered HumanAgent is required")


def _refuse_human_only(g: Graph, base: str, state: "str | None", agent: "str | None",
                       step: "str | None" = None, target: "str | None" = None, record: bool = False) -> None:
    """Exit with the refusal of `promote` when a human-only rung is set by an agent that is not a registered HumanAgent.
    With record=True (`--record-refusals`) the refusal is also written to the graph as an aiprov:Refusal."""
    if state and canon_rung(state) in HUMAN_ONLY and not _is_human(g, base, agent):
        if record and step and target:
            _record_refusal(base, agent, step, target, canon_rung(state))
        sys.exit(f"REFUSED: rung '{canon_rung(state)}' is human-only; {_not_human_reason(agent)}. An AI must never grant this rung.")


def _clean_state(state: str) -> str:
    """A state as one lower-case token; any other form is read as a different state by validate and report."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", state):
        sys.exit(f"invalid state '{state}': use one token of letters, digits and hyphens")
    return state.lower()


def cmd_claim(a) -> None:
    g = load()
    a.state = _clean_state(a.state)
    _require_registered(g, a.base, a.agent)
    _refuse_human_only(g, a.base, a.state, a.agent, "claim", a.id, getattr(a, "record_refusals", False))
    c = ns(a.base, "claim")[a.id]
    g.add((c, RDF.type, AIPROV.Claim))
    g.add((c, RDFS.label, Literal(a.text, lang="en")))
    g.add((c, PROV.wasGeneratedBy, ns(a.base, "activity")[a.parent]))
    g.add((c, PROV.wasAttributedTo, ns(a.base, "agent")[a.agent]))
    g.add((c, AIPROV.verificationState, ns(a.base, "verification")[a.state]))
    save(g)
    print(f"claim:{a.id} added (state {a.state})")


DATA_CLASSES = ["public", "untrusted", "internal", "confidential", "restricted"]
KEEP_TEXT_OK = {"public", "untrusted", "internal"}  # classes in which message text may be stored
_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")


def _channel_value(g: Graph, chan, prop, value, flag: str) -> None:
    """Write-once channel attribute: add while absent, refuse a different second value."""
    old = set(g.objects(chan, prop))
    if old and Literal(value) not in old:
        sys.exit(f"{flag}: the channel already has {', '.join(str(o) for o in old)}; a recorded value is not replaced")
    g.add((chan, prop, Literal(value)))


def cmd_message(a) -> None:
    """Record one message of a registered agent in a channel (issue 43). The content hash is always written; the
    text only with --keep-text. Nothing is guessed: without --sent-at there is no aiprov:sentAt."""
    g = load()
    _require_registered(g, a.base, a.agent)
    if (a.text is None) == (a.content_hash is None):
        sys.exit("give exactly one of --text and --content-hash")
    if a.keep_text and a.text is None:
        sys.exit("--keep-text needs --text")
    if a.content_hash is not None and not _HASH_RE.fullmatch(a.content_hash):
        sys.exit("--content-hash: use sha256:<64 hex digits>")
    msg = ns(a.base, "message")[a.id]
    if (msg, RDF.type, None) in g:
        sys.exit(f"message {a.id} is already logged; the graph is append-only, use a new id")
    chan = ns(a.base, "channel")[a.channel]
    if (chan, RDF.type, None) in g and (chan, RDF.type, AIPROV.Channel) not in g:
        sys.exit(f"{chan} exists and is not a channel")
    if a.reply_to:
        target = ns(a.base, "message")[a.reply_to]
        if target == msg:
            sys.exit("--reply-to: a message cannot reply to itself")
        if (target, RDF.type, AIPROV.Message) not in g:
            sys.exit(f"--reply-to: message {a.reply_to} is not logged in this graph; a reply target in another "
                     "graph is not supported yet")
    for iri in a.refers_to or []:
        if not iri.startswith(("http://", "https://")):
            sys.exit(f"--refers-to: {iri} is not an http(s) IRI")
    sent = _session_time(a.sent_at, "--sent-at") if a.sent_at else None
    g.add((chan, RDF.type, AIPROV.Channel))
    for val, prop, flag in ((a.platform, AIPROV.platform, "--platform"), (a.channel_name, AIPROV.channelName, "--channel-name"),
                            (a.channel_class, AIPROV.dataClass, "--channel-class")):
        if val is not None:
            _channel_value(g, chan, prop, val, flag)
    g.add((msg, RDF.type, AIPROV.Message))
    g.add((msg, PROV.wasAttributedTo, ns(a.base, "agent")[a.agent]))
    g.add((msg, AIPROV.inChannel, chan))
    if sent is not None:
        g.add((msg, AIPROV.sentAt, sent))
    g.add((msg, AIPROV.recordedAtTime, now()))
    digest = a.content_hash if a.text is None else "sha256:" + hashlib.sha256(a.text.encode("utf-8")).hexdigest()
    g.add((msg, AIPROV.contentHash, Literal(digest)))
    if a.keep_text:
        g.add((msg, AIPROV.content, Literal(a.text)))
    if a.reply_to:
        g.add((msg, AIPROV.inReplyTo, ns(a.base, "message")[a.reply_to]))
    for iri in a.refers_to or []:
        g.add((msg, AIPROV.refersTo, URIRef(iri)))
    save(g)
    kept = "text kept" if a.keep_text else "hash only"
    print(f"message:{a.id} logged in channel:{a.channel} ({kept})")


# --- decision records (issue 44) ---------------------------------------------------------------------------------
DECISION_STATES = ["open", "provisional", "done"]
_OPT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_decision(g: Graph, node) -> bool:
    return (node, RDF.type, AIPROV.Decision) in g


def _deciding_acts(g: Graph, dec) -> list:
    """The aiprov:Deciding activities that used this decision, oldest record first."""
    acts = [x for x in g.subjects(PROV.used, dec) if (x, RDF.type, AIPROV.Deciding) in g]
    return sorted(acts, key=lambda x: (str(g.value(x, AIPROV.recordedAtTime) or ""), str(x)))


def _decision_state(g: Graph, dec) -> str:
    """Effective state: the state set by the latest Deciding activity, else open."""
    acts = _deciding_acts(g, dec)
    if not acts:
        return "open"
    st = g.value(acts[-1], AIPROV.decisionState)
    return str(st).rsplit("decisionState-", 1)[-1] if st is not None else "open"


def _supersedes_chain(g: Graph, start) -> set:
    seen, todo = set(), [start]
    while todo:
        n = todo.pop()
        for o in g.objects(n, AIPROV.supersedes):
            if o not in seen:
                seen.add(o)
                todo.append(o)
    return seen


def _decision_open(g: Graph, a) -> None:
    _require_registered(g, a.base, a.agent)
    dec = ns(a.base, "decision")[a.id]
    if (dec, RDF.type, None) in g:
        sys.exit(f"decision {a.id} is already logged; the graph is append-only, use a new id")
    if not a.question:
        sys.exit("decision open needs --question")
    opts: dict = {}
    for spec in a.option or []:
        oid, sep, text = spec.partition("=")
        if not sep or not _OPT_RE.fullmatch(oid) or not text:
            sys.exit(f"--option: use ID=TEXT with an id of letters, digits, '-' and '_' (got '{spec}')")
        if oid in opts:
            sys.exit(f"--option: option {oid} is given twice")
        opts[oid] = text
    if len(opts) < 2:
        sys.exit("a decision offers at least two --option ID=TEXT")
    if a.recommend and a.recommend not in opts:
        sys.exit(f"--recommend: {a.recommend} is not one of the options")
    if a.keep_text and a.data_class not in KEEP_TEXT_OK:
        sys.exit("--keep-text needs --data-class public, untrusted or internal; the text of a question and its "
                 "options may carry project content")
    for iri in [a.asked_in] if a.asked_in else []:
        if not iri.startswith(("http://", "https://")):
            sys.exit(f"--asked-in: {iri} is not an http(s) IRI")
    g.add((dec, RDF.type, AIPROV.Decision))
    g.add((dec, PROV.wasAttributedTo, ns(a.base, "agent")[a.agent]))
    g.add((dec, AIPROV.decisionState, AIPROV["decisionState-open"]))
    g.add((dec, AIPROV.contentHash, Literal(_digest(a.question))))
    if a.keep_text:
        g.add((dec, RDFS.label, Literal(a.question)))
    if a.data_class:
        g.add((dec, AIPROV.dataClass, Literal(a.data_class)))
    if a.asked_in:
        g.add((dec, AIPROV.askedIn, URIRef(a.asked_in)))
    g.add((dec, AIPROV.recordedAtTime, now()))
    for oid, text in opts.items():
        o = ns(a.base, "option")[f"{a.id}-{oid}"]
        g.add((o, RDF.type, AIPROV.Option))
        g.add((o, AIPROV.optionOf, dec))
        g.add((o, AIPROV.contentHash, Literal(_digest(text))))
        if a.keep_text:
            g.add((o, RDFS.label, Literal(text)))
    if a.recommend:
        g.add((dec, AIPROV.recommendedOption, ns(a.base, "option")[f"{a.id}-{a.recommend}"]))
    save(g)
    print(f"decision:{a.id} opened with {len(opts)} options ({'text kept' if a.keep_text else 'hash only'})")


def _decision_decide(g: Graph, a) -> None:
    dec = ns(a.base, "decision")[a.id]
    if not _is_decision(g, dec):
        sys.exit(f"decision {a.id} is not logged; open it with `provlog decision open` first")
    _require_registered(g, a.base, a.agent)
    if not a.choose:
        sys.exit("decision decide needs --choose OPTION")
    opt = ns(a.base, "option")[f"{a.id}-{a.choose}"]
    if (opt, AIPROV.optionOf, dec) not in g:
        sys.exit(f"--choose: {a.choose} is not an option of decision {a.id}")
    if a.state == "done":
        # one rule with the human-only rungs (issue 22): only a registered HumanAgent closes a decision
        if not _is_human(g, a.base, a.agent):
            sys.exit(f"REFUSED: state 'done' is human-only; {_not_human_reason(a.agent)}. An AI may set 'provisional' only.")
    if _decision_state(g, dec) == "done":
        sys.exit(f"decision {a.id} is done; a changed decision is a new decision that supersedes it")
    if a.decided_in and not a.decided_in.startswith(("http://", "https://")):
        sys.exit(f"--decided-in: {a.decided_in} is not an http(s) IRI")
    decided = _session_time(a.decided_at, "--decided-at") if a.decided_at else now()
    n = len(_deciding_acts(g, dec)) + 1
    act = ns(a.base, "activity")[f"decide-{a.id}-{n}"]
    g.add((act, RDF.type, AIPROV.Deciding))
    g.add((act, PROV.used, dec))
    g.add((act, PROV.wasAssociatedWith, ns(a.base, "agent")[a.agent]))
    g.add((act, AIPROV.chosenOption, opt))
    g.add((act, AIPROV.decisionState, AIPROV["decisionState-" + a.state]))
    if a.decided_in:
        g.add((act, AIPROV.decidedIn, URIRef(a.decided_in)))
    g.add((act, PROV.endedAtTime, decided))
    g.add((act, AIPROV.recordedAtTime, now()))
    save(g)
    print(f"decision:{a.id} {a.state}: option {a.choose} chosen by agent:{a.agent}")


def _decision_supersede(g: Graph, a) -> None:
    new, old = ns(a.base, "decision")[a.id], ns(a.base, "decision")[a.old or ""]
    if not a.old:
        sys.exit("decision supersede needs --old DECISION")
    if not _is_decision(g, new):
        sys.exit(f"decision {a.id} is not logged")
    if not _is_decision(g, old):
        sys.exit(f"--old: decision {a.old} is not logged")
    if new == old:
        sys.exit("a decision cannot supersede itself")
    if new in _supersedes_chain(g, old):
        sys.exit(f"decision {a.old} already supersedes {a.id}; that would be a cycle")
    if (new, AIPROV.supersedes, old) in g:
        sys.exit(f"decision {a.id} already supersedes {a.old}")
    g.add((new, AIPROV.supersedes, old))
    save(g)
    print(f"decision:{a.id} supersedes decision:{a.old}")


def cmd_decision(a) -> None:
    g = load()
    {"open": _decision_open, "decide": _decision_decide, "supersede": _decision_supersede}[a.action](g, a)


# --- bulk telemetry tier (issue 15) ------------------------------------------------------------------------------
# Volume that would inflate the graph (one record per request or tool run) goes to a JSONL file in which every line
# carries the hash of the line before it; the graph records only the head of the chain and its length.
_CHAIN_GENESIS = "sha256:" + "0" * 64


def _canon(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _chain_hash(prev: str, seq: int, data_json: str) -> str:
    return "sha256:" + hashlib.sha256(f"{prev}\n{seq}\n{data_json}".encode("utf-8")).hexdigest()


def _check_line(raw: str, seq: "int | None" = None, prev: "str | None" = None) -> dict:
    """Parse one chain line and check its shape and its own hash; raises ValueError with the reason."""
    try:
        rec = json.loads(raw)
    except ValueError:
        raise ValueError("not JSON")
    if (not isinstance(rec, dict) or set(rec) != {"seq", "prev", "data", "hash"} or not isinstance(rec["data"], dict)
            or type(rec["seq"]) is not int or not isinstance(rec["prev"], str) or not isinstance(rec["hash"], str)):
        raise ValueError("not a chain record")
    if seq is not None and rec["seq"] != seq:
        raise ValueError(f"seq is {rec['seq']}, expected {seq}")
    if prev is not None and rec["prev"] != prev:
        raise ValueError("prev does not match the line before")
    if rec["hash"] != _chain_hash(rec["prev"], rec["seq"], _canon(rec["data"])):
        raise ValueError("hash does not match the content")
    return rec


def _verify_chain(path: pathlib.Path) -> "tuple[list, str | None]":
    """Walk the whole file. Returns (heads, error): heads[i] is the head after i records; error names the first bad line."""
    heads = [_CHAIN_GENESIS]
    with open(path, encoding="utf-8", newline="") as f:
        for ln, raw in enumerate(f, 1):
            if not raw.endswith("\n"):
                return heads, f"line {ln}: incomplete last line (no newline)"
            try:
                rec = _check_line(raw[:-1], ln, heads[-1])
            except ValueError as e:
                return heads, f"line {ln}: {e}"
            heads.append(rec["hash"])
    return heads, None


def _last_line(f, size: int) -> "bytes | None":
    if size == 0:
        return None
    pos, buf = size, b""
    while pos > 0:
        step = min(65536, pos)
        pos -= step
        f.seek(pos)
        buf = f.read(step) + buf
        body = buf[:-1]  # the final newline is the terminator, not a separator
        if b"\n" in body:
            return body.rsplit(b"\n", 1)[1]
    return buf[:-1]


def _bulk_data(a) -> dict:
    if (a.data is None) == (a.data_file is None):
        sys.exit("give exactly one of --data and --data-file")
    raw = a.data if a.data is not None else pathlib.Path(a.data_file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except ValueError as e:
        sys.exit(f"data: not valid JSON ({e})")
    if not isinstance(data, dict):
        sys.exit("data: give one JSON object")
    return data


def _bulk_append(a) -> None:
    data = _bulk_data(a)
    path = pathlib.Path(a.file)
    with open(path, "ab+") as f:
        if fcntl is not None:
            fcntl.flock(f, fcntl.LOCK_EX)
        size = f.seek(0, 2)
        if size:
            f.seek(size - 1)
            if f.read(1) != b"\n":
                sys.exit(f"{path.name}: the last line is incomplete; run `bulk verify`, nothing was appended")
        last = _last_line(f, size)
        if last is None:
            prev, seq = _CHAIN_GENESIS, 1
        else:
            try:
                rec = _check_line(last.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                sys.exit(f"{path.name}: the last line is not a valid chain record ({e}); nothing was appended")
            prev, seq = rec["hash"], rec["seq"] + 1
        digest = _chain_hash(prev, seq, _canon(data))
        line = json.dumps({"seq": seq, "prev": prev, "data": data, "hash": digest}, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False)
        f.write((line + "\n").encode("utf-8"))
    print(f"bulk: record {seq} appended to {path.name}; head {digest}")


def _bulk_verify(a) -> None:
    path = pathlib.Path(a.file)
    if not path.exists():
        sys.exit(f"{path}: no such file")
    heads, err = _verify_chain(path)
    if err:
        sys.exit(f"chain broken in {path.name}, {err}")
    n = len(heads) - 1
    print(f"chain ok: {n} records, head {heads[-1]}")
    if a.anchor:
        g = load()
        node = ns(a.base, "chain")[a.anchor]
        if (node, RDF.type, AIPROV.TelemetryChain) not in g:
            sys.exit(f"anchor {a.anchor} is not a telemetry chain of this graph")
        head, length = g.value(node, AIPROV.chainHead), g.value(node, AIPROV.chainLength)
        if head is None or length is None or not isinstance(length.toPython(), int):
            sys.exit(f"anchor {a.anchor} has no valid head and length")
        length = length.toPython()
        if n < length:
            sys.exit(f"anchor {a.anchor} covers {length} records but the file has only {n}: records are missing")
        if str(head) != heads[length]:
            sys.exit(f"anchor {a.anchor}: the head after {length} records is {heads[length]}, the graph recorded {head}: "
                     "the file differs from what was anchored")
        print(f"anchor {a.anchor} holds: the first {length} records match the head in the graph"
              + (f" ({n - length} appended since)" if n > length else ""))


def _bulk_anchor(a) -> None:
    g = load()
    _require_registered(g, a.base, a.agent)
    node = ns(a.base, "chain")[a.id]
    if (node, RDF.type, None) in g:
        sys.exit(f"chain anchor {a.id} is already logged; the graph is append-only, use a new id")
    path = pathlib.Path(a.file)
    if not path.exists():
        sys.exit(f"{path}: no such file")
    heads, err = _verify_chain(path)
    if err:
        sys.exit(f"chain broken in {path.name}, {err}; nothing was anchored")
    n = len(heads) - 1
    if a.upto is not None:
        if not 1 <= a.upto <= n:
            sys.exit(f"--upto: give a number from 1 to {n}")
        n = a.upto
    if n < 1:
        sys.exit(f"{path.name} has no records; nothing to anchor")
    g.add((node, RDF.type, AIPROV.TelemetryChain))
    g.add((node, PROV.wasAttributedTo, ns(a.base, "agent")[a.agent]))
    g.add((node, AIPROV.chainHead, Literal(heads[n])))
    g.add((node, AIPROV.chainLength, Literal(n, datatype=XSD.integer)))
    g.add((node, AIPROV.recordedAtTime, now()))
    save(g)
    print(f"chain:{a.id} anchored: {n} records, head {heads[n]}")


def cmd_bulk(a) -> None:
    {"append": _bulk_append, "verify": _bulk_verify, "anchor": _bulk_anchor}[a.action](a)


def _decision_findings(g: Graph) -> list:
    """(severity, label, rows) for validate. FAIL: malformed decision, option not offered, `done` without a registered
    human, bad supersede. WARN: kept text where the data class is unknown or above internal."""
    malformed, badopt, notoffered, ndone, badsup, risky = [], [], [], [], [], []
    for d in set(g.subjects(RDF.type, AIPROV.Decision)):
        opts = set(g.subjects(AIPROV.optionOf, d))
        h, txt = g.value(d, AIPROV.contentHash), g.value(d, RDFS.label)
        if (d, PROV.wasAttributedTo, None) not in g or h is None or len(opts) < 2 \
                or (txt is not None and str(h) != _digest(str(txt))):
            malformed.append((d,))
        rec = g.value(d, AIPROV.recommendedOption)
        if rec is not None and rec not in opts:
            malformed.append((d,))
        if txt is not None or any((o, RDFS.label, None) in g for o in opts):
            cls = {str(c) for c in g.objects(d, AIPROV.dataClass)}
            if not cls or not cls <= KEEP_TEXT_OK:
                risky.append((d,))
        for t in g.objects(d, AIPROV.supersedes):
            if t == d or not _is_decision(g, t) or d in _supersedes_chain(g, t):
                badsup.append((d,))
    for o in set(g.subjects(RDF.type, AIPROV.Option)):
        d, h, txt = g.value(o, AIPROV.optionOf), g.value(o, AIPROV.contentHash), g.value(o, RDFS.label)
        if d is None or not _is_decision(g, d) or h is None or (txt is not None and str(h) != _digest(str(txt))):
            badopt.append((o,))
    for act in set(g.subjects(RDF.type, AIPROV.Deciding)):
        used = [u for u in g.objects(act, PROV.used) if _is_decision(g, u)]
        chosen = list(g.objects(act, AIPROV.chosenOption))
        states = [str(s).rsplit("decisionState-", 1)[-1] for s in g.objects(act, AIPROV.decisionState)]
        who = list(g.objects(act, PROV.wasAssociatedWith))
        if len(used) != 1 or len(chosen) != 1 or len(states) != 1 or states[0] not in DECISION_STATES or not who:
            badopt.append((act,))
            continue
        if (chosen[0], AIPROV.optionOf, used[0]) not in g:
            notoffered.append((act,))
        if states[0] == "done" and not all((w, RDF.type, AIPROV.HumanAgent) in g for w in who):
            ndone.append((act,))
    return [("FAIL", "decisions that are malformed (asker, hash, two options, recommendation, text matching hash)", malformed),
            ("FAIL", "options or deciding activities that are incomplete", badopt),
            ("FAIL", "chosen options that the decision did not offer", notoffered),
            ("FAIL", "decisions set to done by an agent that is not a registered human", ndone),
            ("FAIL", "supersedes links to a missing decision, to itself or in a cycle", badsup),
            ("WARN", "decision text kept where the data class is unknown or above internal", risky)]


# --- schema versions and migration (issue 42) ---------------------------------------------------------------
SCHEMA_VERSION = "0.3.0"  # the schema version this provlog writes
SCHEMA_VERSIONS = ["0.1.0", "0.2.0", "0.3.0"]  # every version a graph can have; add the new one at each release
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def _vkey(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def graph_version(g: Graph) -> "tuple[str, bool]":
    """The schema version of g and whether the graph states it. A graph without aiprov:schemaVersion is
    detected by its terms: the vocabulary of 0.2.0 has aiprov:Orchestration, that of 0.1.0 does not."""
    stamped = [str(o) for o in g.objects(None, AIPROV.schemaVersion) if _VERSION_RE.fullmatch(str(o))]
    if stamped:
        return max(stamped, key=_vkey), True
    if (AIPROV.Orchestration, RDF.type, None) in g or (AIPROV.plannedRole, RDF.type, None) in g:
        return "0.2.0", False
    return "0.1.0", False


def stamp_version(g: Graph, base: str, version: str) -> None:
    """Make `version` the only aiprov:schemaVersion of g, on the node that carries it already (else <base>graph)."""
    node = next(iter(g.subjects(AIPROV.schemaVersion, None)), URIRef(base + "graph"))
    for old in list(g.triples((None, AIPROV.schemaVersion, None))):
        g.remove(old)
    g.add((node, AIPROV.schemaVersion, Literal(version)))


def _deprecate(g: Graph, term) -> int:
    """Mark a term as deprecated instead of deleting it (for the steps of future releases); 1 if newly marked."""
    mark = (term, OWL.deprecated, Literal(True))
    if mark in g:
        return 0
    g.add(mark)
    return 1


def _step_no_change(g: Graph) -> int:
    """A release that only adds terms needs no rewrite; the vocabulary refresh brings the new terms."""
    return 0


# key: the version migrated FROM; the step leads to the next entry of SCHEMA_VERSIONS and returns the number of
# terms it marked deprecated. A release that changes a term adds its step here and keeps the previous fixture.
MIGRATION_STEPS = {"0.1.0": _step_no_change, "0.2.0": _step_no_change}


def apply_steps(g: Graph, frm: str, to: str) -> int:
    deprecated = 0
    for v in SCHEMA_VERSIONS[SCHEMA_VERSIONS.index(frm):SCHEMA_VERSIONS.index(to)]:
        deprecated += MIGRATION_STEPS[v](g)
    return deprecated


def upgrade_in_memory(g: Graph) -> Graph:
    """Run the steps to the current version on g without stamping or refreshing; readers (dashboard) use this so
    they understand a graph of any version while the file stays as it is."""
    frm, _ = graph_version(g)
    if frm in SCHEMA_VERSIONS and frm != SCHEMA_VERSION:
        apply_steps(g, frm, SCHEMA_VERSION)
    return g


def _vocabulary(base: str) -> Graph:
    v = Graph()
    v.parse(data=SCHEMA.read_text(encoding="utf-8").replace("https://example.org/prov/", base), format="turtle")
    return v


def _tool_version() -> str:
    try:
        from importlib.metadata import version
        return version("aiprov")
    except Exception:  # noqa: BLE001 - not installed as a package: fall back to the module constant
        from aiprov import __version__
        return __version__


def cmd_migrate(a) -> None:
    if not GRAPH.exists():
        sys.exit("no provenance.ttl in this directory; nothing to migrate")
    g = load()
    frm, stamped = graph_version(g)
    to = a.to or SCHEMA_VERSION
    if to not in SCHEMA_VERSIONS:
        sys.exit(f"unknown target version {to}; known: {', '.join(SCHEMA_VERSIONS)}")
    if frm not in SCHEMA_VERSIONS:
        sys.exit(f"the graph is at schema version {frm}, newer than this provlog knows; update aiprov")
    if _vkey(to) < _vkey(frm):
        sys.exit(f"refused: the graph is at {frm}; migrating down to {to} is not supported")
    _require_registered(g, a.base, a.agent)
    started = now()
    before = set(g)
    deprecated = apply_steps(g, frm, to)
    if to == SCHEMA_VERSION:  # add vocabulary terms that are missing; a term already there is never touched
        for t in _vocabulary(a.base):
            g.add(t)
    stamp_version(g, a.base, to)
    after = set(g)
    added, removed = after - before, before - after
    if not added and not removed:
        print(f"graph is at schema version {frm}; nothing to migrate")
        return
    how = "" if stamped else " (version detected from the terms)"
    summary = (f"{frm} -> {to}{how}: {len(g)} triples ({len(added) - len(removed):+d}), "
               f"{len(added)} added, {deprecated} marked deprecated")
    if a.dry_run:
        print("dry run, nothing written. Would migrate " + summary)
        return
    act = ns(a.base, "activity")[f"migrate-{frm}-to-{to}-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")]
    n = 1
    while (act, RDF.type, None) in g:
        n += 1
        act = ns(a.base, "activity")[f"migrate-{frm}-to-{to}-{n}"]
    g.add((act, RDF.type, AIPROV.Migration))
    g.add((act, RDFS.label, Literal(f"Schema migration {frm} -> {to}", lang="en")))
    g.add((act, PROV.startedAtTime, started))
    g.add((act, PROV.endedAtTime, now()))
    g.add((act, AIPROV.fromSchemaVersion, Literal(frm)))
    g.add((act, AIPROV.toSchemaVersion, Literal(to)))
    g.add((act, AIPROV.toolVersion, Literal(_tool_version())))
    g.add((act, AIPROV.addedTriples, Literal(len(added), datatype=XSD.integer)))
    g.add((act, AIPROV.deprecatedTriples, Literal(deprecated, datatype=XSD.integer)))
    if a.agent:
        g.add((act, PROV.wasAssociatedWith, ns(a.base, "agent")[a.agent]))
    save(g)
    print(f"migrated {summary}; activity {act.rsplit('/', 1)[-1]}")


def validate_graph(g: Graph) -> int:
    """Run all conformance checks on g, print them, return the number of failures."""
    fail = 0
    q1 = """SELECT ?c WHERE { ?c a aiprov:Claim .
            FILTER NOT EXISTS { ?c prov:wasGeneratedBy ?x } }"""
    orphans = list(g.query(q1))
    print(f"[{'FAIL' if orphans else ' OK '}] parentless claims: {len(orphans)}")
    fail += len(orphans)
    q2 = """SELECT ?c WHERE { ?c a aiprov:Claim .
            FILTER NOT EXISTS { ?c prov:wasAttributedTo ?x } }"""
    unattr = list(g.query(q2))
    print(f"[{'FAIL' if unattr else ' OK '}] unattributed claims: {len(unattr)}")
    fail += len(unattr)
    # Human-only rungs: the offence is WHO GRANTED the rung, not who authored
    # the claim. Promotions are AuditPass activities labelled "... -> <rung>";
    # an AI agent associated with such a promotion is a hard failure.
    q3 = """SELECT ?act ?ag WHERE {
              ?act a aiprov:AuditPass ; rdfs:label ?l ;
                   prov:wasAssociatedWith ?ag .
              ?ag a aiprov:AIAgent .
              FILTER(REGEX(STR(?l), "-> (human-confirmed|human-read|lit-read)")) }"""
    bad = list(g.query(q3))
    print(f"[{'FAIL' if bad else ' OK '}] human-only rungs granted by AI agents: {len(bad)}")
    fail += len(bad)
    # Softer check: node sits at a human-only rung but the graph records no
    # human-associated promotion activity for it. Legitimate for legacy or
    # hand-curated graphs, so WARN, not FAIL.
    q3w = """SELECT ?n WHERE {
              ?n aiprov:verificationState ?s .
              FILTER(REGEX(STR(?s), "(human-confirmed|human-read|lit-read)$"))
              FILTER NOT EXISTS {
                ?act prov:used ?n ; prov:wasAssociatedWith ?h .
                ?h a aiprov:HumanAgent . } }"""
    unwit = list(g.query(q3w))
    print(f"[{'WARN' if unwit else ' OK '}] human-only rungs without a recorded "
          f"human promotion activity: {len(unwit)}")
    q3b = """SELECT ?s ?st WHERE { ?s a aiprov:Source ;
              aiprov:verificationState ?st .
            FILTER(REGEX(STR(?st), "(retrieved|reference-resolved|ai-confirmed|source-vendored|human-confirmed|human-read|lit-read)$"))
            FILTER NOT EXISTS { ?s aiprov:doi ?d }
            FILTER NOT EXISTS { ?s <http://purl.org/dc/terms/source> ?u } }"""
    noref = list(g.query(q3b))
    print(f"[{'FAIL' if noref else ' OK '}] sources above needs-research without DOI/URL: {len(noref)}")
    fail += len(noref)
    q4 = """SELECT ?act WHERE { ?e prov:wasGeneratedBy ?act .
            FILTER NOT EXISTS { ?act prov:wasAssociatedWith ?ag } }"""
    anon = set(r[0] for r in g.query(q4))
    print(f"[{'WARN' if anon else ' OK '}] activities without agent: {len(anon)}")
    # An activity that carries a session id describes work done inside a session, so its span is a claim about
    # that work. A span of under a second is almost always the instant the record was appended, which matters
    # because the model in force can change inside a session: attribution then follows the moment of logging
    # rather than the moment of work. Reported, never failed - a genuinely short activity is possible, and
    # aiprov cannot tell the two apart. aiprov:recordedAtTime exists so new records need not be guessed at.
    instants = []
    for act in set(g.subjects(AIPROV.sessionId, None)):
        st, en = g.value(act, PROV.startedAtTime), g.value(act, PROV.endedAtTime)
        if en is None:
            continue
        if st is None:
            instants.append(act)      # no span recorded at all: the end is the moment of writing
            continue
        try:
            span = (en.toPython() - st.toPython()).total_seconds()
        except (TypeError, AttributeError):
            continue
        if span < 1.0:
            instants.append(act)
    print(f"[{'WARN' if instants else ' OK '}] session activities with no measurable span "
          f"(a logging instant, not the span of the work): {len(instants)}")
    # An agent that is named but was never registered carries no type, model or name (issue 21).
    unreg = list(g.query("""SELECT DISTINCT ?ag WHERE {
            { ?x prov:wasAssociatedWith ?ag } UNION { ?x prov:wasAttributedTo ?ag }
            FILTER NOT EXISTS { ?ag a aiprov:AIAgent } FILTER NOT EXISTS { ?ag a aiprov:HumanAgent }
            FILTER NOT EXISTS { ?ag a aiprov:ToolAgent } }"""))
    print(f"[{'FAIL' if unreg else ' OK '}] agents referenced but not registered: {len(unreg)}")
    fail += len(unreg)
    # An agent is an AI or a person, never both (issue 22). There is no automatic repair: it is unknown which type
    # was meant, so the nodes are listed and the wrong rdf:type is removed by hand.
    dual = [(n,) for n in sorted(set(g.subjects(RDF.type, AIPROV.AIAgent)) & set(g.subjects(RDF.type, AIPROV.HumanAgent)))]
    print(f"[{'FAIL' if dual else ' OK '}] agents typed as both AI and human: {len(dual)}")
    fail += len(dual)
    nref = len(set(g.subjects(RDF.type, AIPROV.Refusal)))
    if nref:
        print(f"[INFO] refused human-only steps recorded: {nref}")
    # Orchestration (multi-agent runs): delegation links must resolve and obey the declared plan.
    dangling = list(g.query("""SELECT ?a ?p WHERE { ?a prov:wasInformedBy ?p .
            FILTER NOT EXISTS { ?p prov:endedAtTime ?t }
            FILTER NOT EXISTS { ?p rdfs:isDefinedBy ?elsewhere } }"""))
    print(f"[{'FAIL' if dangling else ' OK '}] wasInformedBy targets that are not logged activities: {len(dangling)}")
    fail += len(dangling)
    print(f"[ OK ] external references (nodes defined in another graph): {len(_external_refs(g))}")
    unplanned_agent = list(g.query("""SELECT ?a ?ag WHERE { ?a prov:wasInformedBy ?o ;
            prov:wasAssociatedWith ?ag . ?o a aiprov:Orchestration ; aiprov:plannedAgent ?any .
            FILTER NOT EXISTS { ?o aiprov:plannedAgent ?ag } }"""))
    unplanned_role = list(g.query("""SELECT ?a ?r WHERE { ?a prov:wasInformedBy ?o ; aiprov:role ?r .
            ?o a aiprov:Orchestration ; aiprov:plannedRole ?anyr .
            FILTER NOT EXISTS { ?o aiprov:plannedRole ?r } }"""))
    missing_agent = list(g.query("""SELECT ?a WHERE { ?a prov:wasInformedBy ?o .
            ?o a aiprov:Orchestration ; aiprov:plannedAgent ?x .
            FILTER NOT EXISTS { ?a prov:wasAssociatedWith ?ag } }"""))
    missing_role = list(g.query("""SELECT ?a WHERE { ?a prov:wasInformedBy ?o .
            ?o a aiprov:Orchestration ; aiprov:plannedRole ?x .
            FILTER NOT EXISTS { ?a aiprov:role ?r } }"""))
    wrong_binding = list(g.query("""SELECT ?a WHERE { ?a prov:wasInformedBy ?o ;
            prov:wasAssociatedWith ?ag ; aiprov:role ?r .
            ?o a aiprov:Orchestration ; aiprov:plannedBinding ?b0 .
            FILTER(STRSTARTS(?b0, CONCAT(STR(?ag), "|")))
            FILTER NOT EXISTS { ?o aiprov:plannedBinding ?b . FILTER(?b = CONCAT(STR(?ag), "|", STR(?r))) } }"""))
    unplanned = unplanned_agent + unplanned_role + missing_agent + missing_role + wrong_binding
    print(f"[{'FAIL' if unplanned else ' OK '}] sub-activities outside the orchestration plan: {len(unplanned)}")
    fail += len(unplanned)
    reclosed = list(g.query("""SELECT ?o WHERE { ?o a aiprov:Orchestration ; prov:endedAtTime ?t1, ?t2 .
            FILTER(?t1 < ?t2) }""")) + list(g.query("""SELECT ?o WHERE { ?o a aiprov:Orchestration ;
            prov:wasInformedBy ?o }"""))
    print(f"[{'FAIL' if reclosed else ' OK '}] orchestrations logged twice or informed by themselves: {len(reclosed)}")
    fail += len(reclosed)
    early = list(g.query("""SELECT ?a ?o WHERE { ?a prov:wasInformedBy ?o ; prov:endedAtTime ?at .
            ?o a aiprov:Orchestration ; prov:endedAtTime ?ot . FILTER(?at < ?ot) }"""))
    print(f"[{'FAIL' if early else ' OK '}] sub-activities logged before their orchestration: {len(early)}")
    fail += len(early)
    # Several models per answer: one answer comes from one activity; a fallback replaces a logged, other activity.
    twice = list(g.query("""SELECT DISTINCT ?e WHERE { ?e prov:wasGeneratedBy ?a1, ?a2 .
            ?a1 aiprov:modelRole ?r1 . ?a2 aiprov:modelRole ?r2 . FILTER(?a1 != ?a2) }"""))
    print(f"[{'FAIL' if twice else ' OK '}] entities generated by two activities that carry a model role: {len(twice)}")
    fail += len(twice)
    badfb = list(g.query("""SELECT ?a ?b WHERE { ?a aiprov:fallbackOf ?b .
            FILTER(?a = ?b || NOT EXISTS { ?b prov:endedAtTime ?t }) }"""))
    print(f"[{'FAIL' if badfb else ' OK '}] fallbackOf targets that are not other logged activities: {len(badfb)}")
    fail += len(badfb)
    # Sessions: an activity that says it is part of something must name a session of this graph.
    badpart = list(g.query("""SELECT ?a ?s WHERE { ?a dcterms:isPartOf ?s ; prov:endedAtTime ?t .
            FILTER NOT EXISTS { ?s a aiprov:Session } }"""))
    print(f"[{'FAIL' if badpart else ' OK '}] activities that are part of something that is not a session: {len(badpart)}")
    fail += len(badpart)
    # Messages (issue 43): a sender, a reply target in this graph, a content hash that fits the kept text.
    nosender = list(g.query("""SELECT ?m WHERE { ?m a aiprov:Message .
            FILTER NOT EXISTS { ?m prov:wasAttributedTo ?ag } }"""))
    print(f"[{'FAIL' if nosender else ' OK '}] messages without a sender: {len(nosender)}")
    fail += len(nosender)
    badreply = list(g.query("""SELECT ?m ?t WHERE { ?m aiprov:inReplyTo ?t .
            FILTER(?m = ?t || NOT EXISTS { ?t a aiprov:Message }) }"""))
    print(f"[{'FAIL' if badreply else ' OK '}] replies to a message that is not in this graph: {len(badreply)}")
    fail += len(badreply)
    nohash = list(g.query("""SELECT ?m WHERE { ?m a aiprov:Message .
            FILTER NOT EXISTS { ?m aiprov:contentHash ?h } }"""))
    for m_ in set(g.subjects(RDF.type, AIPROV.Message)):
        txt, hs = g.value(m_, AIPROV.content), g.value(m_, AIPROV.contentHash)
        if txt is not None and hs is not None and str(hs) != "sha256:" + hashlib.sha256(str(txt).encode("utf-8")).hexdigest():
            nohash.append((m_,))
    print(f"[{'FAIL' if nohash else ' OK '}] messages without a content hash, or whose kept text does not match it: {len(nohash)}")
    fail += len(nohash)
    kept_risky = []
    for m_ in set(g.subjects(AIPROV.content, None)):
        cls = {str(c) for ch in g.objects(m_, AIPROV.inChannel) for c in g.objects(ch, AIPROV.dataClass)}
        if not cls or not cls <= KEEP_TEXT_OK:
            kept_risky.append((m_,))
    print(f"[{'WARN' if kept_risky else ' OK '}] message text kept in a channel above internal or of unknown class: {len(kept_risky)}")
    # A record written by someone other than the actor, or after the fact, should name what it was written from.
    unsourced = []
    for act in set(g.subjects(RDF.type, None)):
        if (act, AIPROV.recordedFrom, None) in g:
            continue
        who = set(g.objects(act, PROV.wasAssociatedWith))
        if any(rb not in who for rb in g.objects(act, AIPROV.recordedBy)) or _capture_path(g, act) == "backfill":
            unsourced.append((act,))
    print(f"[{'WARN' if unsourced else ' OK '}] records made by another agent or in arrears without a source (recordedFrom): {len(unsourced)}")
    _, _, twopaths = _witness_split(g)
    print(f"[{'WARN' if twopaths else ' OK '}] sessions with token sums from more than one capture path (only one is counted): {len(twopaths)}")
    # Harness (issue 23): viaHarness must name a registered harness; an activity via a harness should say which model
    # ran or why it is unknown. The second is a WARN: legacy and partial records are legitimate.
    badharness = list(g.query("""SELECT ?a ?h WHERE { ?a aiprov:viaHarness ?h .
            FILTER NOT EXISTS { ?h a aiprov:Harness } }"""))
    print(f"[{'FAIL' if badharness else ' OK '}] viaHarness targets that are not registered harnesses: {len(badharness)}")
    fail += len(badharness)
    nomodel = []
    for act in set(g.subjects(AIPROV.viaHarness, None)):
        if (act, AIPROV.modelUnknownReason, None) in g:
            continue
        if not any((ag, AIPROV.model, None) in g for ag in g.objects(act, PROV.wasAssociatedWith)):
            nomodel.append((act,))
    print(f"[{'WARN' if nomodel else ' OK '}] activities via a harness with neither a model nor a stated reason: {len(nomodel)}")
    # Telemetry chain anchors (issue 15): one valid head, a length of at least 1, an author.
    badchain = []
    for ch_ in sorted(set(g.subjects(RDF.type, AIPROV.TelemetryChain)), key=str):
        heads_, lens_ = list(g.objects(ch_, AIPROV.chainHead)), list(g.objects(ch_, AIPROV.chainLength))
        good = (len(heads_) == 1 and _HASH_RE.fullmatch(str(heads_[0])) is not None and len(lens_) == 1
                and isinstance(lens_[0].toPython(), int) and lens_[0].toPython() >= 1
                and (ch_, PROV.wasAttributedTo, None) in g)
        if not good:
            badchain.append((ch_,))
    print(f"[{'FAIL' if badchain else ' OK '}] telemetry chain anchors without one valid head, a length of at least 1 and an author: {len(badchain)}")
    fail += len(badchain)
    # Decisions (issue 44)
    for sev, label, rows in _decision_findings(g):
        print(f"[{sev if rows else ' OK '}] {label}: {len(rows)}")
        if sev == "FAIL":
            fail += len(rows)
        for row in rows:
            print("   ↳", label + ":", row[0])
    unversioned = not any(True for _ in g.subjects(AIPROV.schemaVersion, None))
    print(f"[{'WARN' if unversioned else ' OK '}] graph states its schema version"
          + (" (none; run `provlog migrate`)" if unversioned else ""))
    for kind, rows in (("parentless claim", orphans), ("unattributed claim", unattr),
                       ("human-only rung granted by an AI agent", bad), ("source without reference", noref),
                       ("human-only rung without human promotion", unwit),
                       ("agent referenced but not registered", unreg),
                       ("agent typed as both AI and human (remove the wrong rdf:type)", dual),
                       ("wasInformedBy target not logged", dangling), ("outside the plan", unplanned),
                       ("orchestration logged twice", reclosed), ("logged before its orchestration", early),
                       ("answer from two model activities", twice), ("bad fallbackOf target", badfb),
                       ("part of a non-session", badpart), ("message without a sender", nosender),
                       ("reply target not a message of this graph", badreply), ("message hash missing or wrong", nohash),
                       ("message text kept in a channel above internal or of unknown class", kept_risky),
                       ("record by another agent or in arrears without a source", unsourced),
                       ("session with token sums from more than one capture path", twopaths),
                       ("viaHarness target is not a registered harness", badharness),
                       ("activity via a harness with neither a model nor a stated reason", nomodel),
                       ("telemetry chain anchor malformed", badchain)):
        for row in rows:
            print("   ↳", kind + ":", row[0])
    return fail


def cmd_validate(a) -> None:
    sys.exit(1 if validate_graph(load()) else 0)


def cmd_report(a) -> None:
    g = load()
    aux, dropped, _twopaths = _witness_split(g)

    def total(prop):
        return sum(int(o) for x, _, o in g.triples((None, prop, None)) if x not in aux and x not in dropped)
    print("== aiprov report ==")
    print(f"triples:            {len(g)}")
    sessions = set(g.subjects(RDF.type, AIPROV.Session))
    print(f"activities:         {len(set(g.subjects(PROV.endedAtTime, None)) - sessions)}")
    print(f"claims:             {len(set(g.subjects(RDF.type, AIPROV.Claim)))}")
    nref = len(set(g.subjects(RDF.type, AIPROV.Refusal)))
    if nref:
        print(f"refusals:           {nref}")
    print(f"input tokens:       {total(AIPROV.inputTokens)}")
    print(f"output tokens:      {total(AIPROV.outputTokens)}")
    print(f"cache read tokens:  {total(AIPROV.cacheReadTokens)}")
    print(f"total tokens:       {total(AIPROV.totalTokens)}")
    cost = sum(float(o) for x, _, o in g.triples((None, AIPROV.cost, None)) if x not in aux and x not in dropped)
    cur = {str(o) for _, _, o in g.triples((None, AIPROV.costCurrency, None))} or {"?"}
    print(f"cost:               {cost:.4f} {'/'.join(sorted(cur))}")
    print("-- tokens per agent --")
    per: dict = {}
    for act, t in g.subject_objects(AIPROV.totalTokens):
        if act in aux or act in dropped:
            continue
        for ag in g.objects(act, PROV.wasAssociatedWith):
            e = per.setdefault(ag, [0, set()])
            e[0] += int(t)
            e[1].add(act)
    for ag, (tok, acts_) in sorted(per.items(), key=lambda kv: (-kv[1][0], str(kv[0]))):
        print(f"   {str(ag).rsplit('/',1)[-1]:24s} {tok:>10} tok  {len(acts_)} activities")
    paths: dict = {}
    for act in set(g.subjects(PROV.endedAtTime, None)) - sessions:
        k = _capture_path(g, act)
        if k:
            paths[k] = paths.get(k, 0) + 1
    if paths or aux or dropped:
        print("-- capture paths --")
        for k in sorted(paths, key=lambda k: CAPTURE_PATHS.index(k) if k in CAPTURE_PATHS else 99):
            print(f"   {k:24s} {paths[k]} activities")
        if aux:
            print(f"   auxiliary passes (tokens kept apart, not in the totals above): {len(aux)} activities, "
                  f"{sum(_act_tokens(g, x) for x in aux)} tokens")
        if dropped:
            print(f"   not counted (the session is already reported by another capture path): {len(dropped)} activities, "
                  f"{sum(_act_tokens(g, x) for x in dropped)} tokens")
    print("-- verification rungs --")
    q = """SELECT ?s (COUNT(?c) AS ?n) WHERE {
            ?c a aiprov:Claim ; aiprov:verificationState ?s } GROUP BY ?s"""
    agg = {}
    for st, n in g.query(q):
        r = canon_rung(str(st).rsplit("/", 1)[-1])
        agg[r] = agg.get(r, 0) + int(n)
    order = lambda r: LADDER.index(r) if r in LADDER else 99
    for r in sorted(agg, key=order):
        print(f"   {r:24s} {agg[r]}")
    final = sorted({(e, act) for e, act in g.subject_objects(PROV.wasGeneratedBy)
                    if any(str(r) in ("answer", "revise") for r in g.objects(act, AIPROV.modelRole))}, key=str)
    fallbacks = list(g.subject_objects(AIPROV.fallbackOf))
    judges = set(g.subjects(RDF.type, AIPROV.Score))
    if final or fallbacks or judges:
        print("-- model answers --")
        for e, act in final:
            ag = next(iter(g.objects(act, PROV.wasAssociatedWith)), None)
            model = next(iter(g.objects(ag, AIPROV.model)), None) if ag is not None else None
            who = "unknown" if ag is None else str(ag).rsplit("/", 1)[-1] + (f" ({model})" if model else "")
            print(f"   {str(e).rsplit('/',1)[-1]:24s} final: {who}")
        why = {}
        for fa, _ in fallbacks:
            for r in g.objects(fa, AIPROV.fallbackReason):
                why[str(r)] = why.get(str(r), 0) + 1
        tail = " (" + ", ".join(f"{k} {v}" for k, v in sorted(why.items())) + ")" if why else ""
        print(f"   fallbacks: {len(fallbacks)}{tail}; judged answers: {len(judges)}")
    if sessions:
        print("-- sessions --")
        kinds = {}
        for s_ in sessions:
            t = next(iter(g.objects(s_, AIPROV.sessionType)), None)
            key = "(no type)" if t is None else str(t).removeprefix(str(AIPROV) + "sessionType-")
            kinds.setdefault(key, []).append(s_)
        for key in sorted(kinds):
            members = kinds[key]
            acts = sum(len(set(g.subjects(DCT.isPartOf, s_))) for s_ in members)
            outs = {}
            for s_ in members:
                for o in g.objects(s_, AIPROV.sessionOutcome):
                    outs[str(o)] = outs.get(str(o), 0) + 1
            tail = ", ".join(f"{k} {v}" for k, v in sorted(outs.items())) or "no outcome recorded"
            print(f"   {key:24s} {len(members)} sessions, {acts} activities, {tail}")
    harnesses = set(g.subjects(RDF.type, AIPROV.Harness))
    if harnesses:
        print("-- harnesses --")
        for h_ in sorted(harnesses, key=str):
            acts = set(g.subjects(AIPROV.viaHarness, h_))
            kind = next(iter(g.objects(h_, AIPROV.harnessKind)), None)
            kind = "(no kind)" if kind is None else str(kind).removeprefix(str(AIPROV) + "harnessKind-")
            variants = sorted({str(v) for x in acts for v in g.objects(x, AIPROV.modelVariant)})
            unknown = sum(1 for x in acts if (x, AIPROV.modelUnknownReason, None) in g)
            tail = (f", variants {', '.join(variants)}" if variants else "") + (f", model unknown {unknown}" if unknown else "")
            print(f"   {str(h_).rsplit('/', 1)[-1]:24s} {kind}, {len(acts)} activities{tail}")
    msgs = set(g.subjects(RDF.type, AIPROV.Message))
    if msgs:
        print("-- messages --")
        chans = {}
        for m_ in msgs:
            for ch in g.objects(m_, AIPROV.inChannel):
                chans.setdefault(ch, []).append(m_)
        for ch in sorted(chans, key=str):
            kept = sum(1 for m_ in chans[ch] if (m_, AIPROV.content, None) in g)
            print(f"   {str(ch).rsplit('/',1)[-1]:24s} {len(chans[ch])} messages, text kept for {kept}")
    chains = set(g.subjects(RDF.type, AIPROV.TelemetryChain))
    if chains:
        print("-- telemetry chains --")
        for c_ in sorted(chains, key=str):
            print(f"   {str(c_).rsplit('/', 1)[-1]:24s} {g.value(c_, AIPROV.chainLength)} records, head {g.value(c_, AIPROV.chainHead)}")
    decs = set(g.subjects(RDF.type, AIPROV.Decision))
    if decs:
        print("-- decisions --")
        by = {}
        for d_ in decs:
            by.setdefault(_decision_state(g, d_), []).append(d_)
        sup = sum(1 for d_ in decs if (None, AIPROV.supersedes, d_) in g)
        print("   " + ", ".join(f"{k} {len(by.get(k, []))}" for k in DECISION_STATES) + f", superseded {sup}")
    roots = set(g.subjects(RDF.type, AIPROV.Orchestration))
    if roots:
        print("-- orchestration --")
        for o in sorted(roots, key=str):
            subs = set(g.subjects(PROV.wasInformedBy, o))
            tok = [int(t) for s_ in subs for t in g.objects(s_, AIPROV.totalTokens)]
            print(f"   {str(o).rsplit('/',1)[-1]:24s} {len(subs)} sub-activities, "
                  + (f"{sum(tok)} tokens reported by {len(tok)}" if tok else "no tokens reported"))


LADDER = ["unverified", "needs-research", "reference-resolved", "ai-confirmed",
          "source-vendored", "human-confirmed", "human-read"]
HUMAN_ONLY = {"human-confirmed", "human-read"}
# Legacy rung names normalize to canonical ones (fair2r lit-*; early aiprov)
RUNG_ALIASES = {"retrieved": "reference-resolved",
                "lit-retrieved": "reference-resolved",
                "ai-checked": "ai-confirmed",
                "lit-read": "human-read"}


def canon_rung(name: str) -> str:
    return RUNG_ALIASES.get(name, name)


def _fetch_doi(doi: str) -> dict | None:
    """Resolve a DOI via Crossref, falling back to OpenAlex. Open APIs, no key."""
    import json as _json
    import urllib.request
    doi = doi.strip().removeprefix("https://doi.org/").removeprefix("doi:")
    for url, pick in [
        (f"https://api.crossref.org/works/{doi}",
         lambda d: {"title": " ".join(d["message"].get("title") or []) or None,
                    "year": (d["message"].get("issued", {}).get("date-parts") or [[None]])[0][0],
                    "container": " ".join(d["message"].get("container-title") or []) or None,
                    "source_api": "crossref"}),
        (f"https://api.openalex.org/works/doi:{doi}",
         lambda d: {"title": d.get("display_name"),
                    "year": d.get("publication_year"),
                    "container": (d.get("primary_location") or {}).get("source", {}).get("display_name"),
                    "source_api": "openalex"}),
    ]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "aiprov-provlog/0.1 (mailto:ops@example.org)"})
            with urllib.request.urlopen(req, timeout=15) as r:
                meta = pick(_json.loads(r.read()))
                meta["doi"] = doi
                return meta
        except Exception:
            continue
    return None


def _set_state(g: Graph, base: str, node, state: str) -> None:
    state = canon_rung(state)
    for old in list(g.objects(node, AIPROV.verificationState)):
        g.remove((node, AIPROV.verificationState, old))
    g.add((node, AIPROV.verificationState, ns(base, "verification")[state]))


def _http_json(url: str):
    import json as _json
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": "aiprov-provlog/0.1 (mailto:ops@example.org)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return _json.loads(r.read())


def cmd_search(a) -> None:
    import urllib.parse
    q = urllib.parse.quote(a.query)
    rows = a.rows
    results, errors = [], []
    backends = a.backend or ["crossref", "openalex"]
    if "crossref" in backends:
        try:
            d = _http_json(f"https://api.crossref.org/works?query={q}&rows={rows}"
                           f"&select=DOI,title,issued,container-title,author,is-referenced-by-count")
            for it in d["message"]["items"]:
                results.append({
                    "doi": it.get("DOI"),
                    "title": " ".join(it.get("title") or ["?"]),
                    "year": (it.get("issued", {}).get("date-parts") or [[None]])[0][0],
                    "venue": " ".join(it.get("container-title") or []) or "—",
                    "cites": it.get("is-referenced-by-count"),
                    "api": "crossref"})
        except Exception as e:
            errors.append(f"crossref: {e}")
    if "openalex" in backends:
        try:
            d = _http_json(f"https://api.openalex.org/works?search={q}&per-page={rows}")
            for it in d.get("results", []):
                doi = (it.get("doi") or "").removeprefix("https://doi.org/") or None
                results.append({
                    "doi": doi, "title": it.get("display_name") or "?",
                    "year": it.get("publication_year"),
                    "venue": ((it.get("primary_location") or {}).get("source") or {}).get("display_name") or "—",
                    "cites": it.get("cited_by_count"), "api": "openalex"})
        except Exception as e:
            errors.append(f"openalex: {e}")
    if "arxiv" in backends:
        try:
            import re
            import urllib.request
            req = urllib.request.Request(
                f"http://export.arxiv.org/api/query?search_query=all:{q}&max_results={rows}",
                headers={"User-Agent": "aiprov-provlog/0.1"})
            xml = urllib.request.urlopen(req, timeout=15).read().decode()
            for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.S):
                e = m.group(1)
                t = re.search(r"<title>(.*?)</title>", e, re.S)
                i = re.search(r"<id>http://arxiv.org/abs/(.*?)</id>", e)
                y = re.search(r"<published>(\d{4})", e)
                doim = re.search(r"<arxiv:doi[^>]*>(.*?)</arxiv:doi>", e)
                results.append({
                    "doi": doim.group(1) if doim else None,
                    "title": " ".join((t.group(1) if t else "?").split()),
                    "year": int(y.group(1)) if y else None,
                    "venue": "arXiv:" + (i.group(1) if i else "?"),
                    "cites": None, "api": "arxiv"})
        except Exception as e:
            errors.append(f"arxiv: {e}")
    if "datacite" in backends:
        try:
            d = _http_json(f"https://api.datacite.org/dois?query={q}&page[size]={rows}")
            for it in d.get("data", []):
                at = it.get("attributes", {})
                results.append({
                    "doi": at.get("doi"),
                    "title": (at.get("titles") or [{}])[0].get("title", "?"),
                    "year": at.get("publicationYear"),
                    "venue": at.get("publisher") or "—",
                    "cites": at.get("citationCount"), "api": "datacite"})
        except Exception as e:
            errors.append(f"datacite: {e}")
    seen, out = set(), []
    for r in results:
        key = r["doi"] or r["title"].lower()
        if key not in seen:
            seen.add(key); out.append(r)
    if not out:
        print("no results" + (f" ({'; '.join(errors)})" if errors else ""))
        return
    print(f"== {len(out)} candidates for: {a.query} ==")
    for r in out:
        c = f" · {r['cites']} cites" if r.get("cites") else ""
        print(f"  [{r['api']:8s}] {r['title'][:78]}")
        print(f"             {r['year'] or '?'} · {r['venue'][:60]}{c}")
        print(f"             doi: {r['doi'] or '— (no DOI; verify manually before use)'}")
    for e in errors:
        print("  (backend unavailable:", e + ")")
    print("Next: provlog.py source --id <slug> --doi <doi> --verify --agent <id>")


def cmd_source(a) -> None:
    g = load()
    s = ns(a.base, "source")[a.id]
    g.add((s, RDF.type, AIPROV.Source))
    state = canon_rung(a.state) if a.state else "unverified"
    _require_registered(g, a.base, a.agent)
    _refuse_human_only(g, a.base, state, a.agent, "source", a.id, getattr(a, "record_refusals", False))
    meta = None
    if a.verify:
        if not a.doi:
            sys.exit("--verify requires --doi")
        meta = _fetch_doi(a.doi)
        if meta is None:
            state = "needs-research"
            print(f"DOI {a.doi} NOT resolvable via Crossref/OpenAlex -> "
                  f"state needs-research (do not cite until resolved)")
        else:
            state = ("reference-resolved"
                     if LADDER.index(state) < LADDER.index("reference-resolved")
                     else state)
            print(f"DOI verified via {meta['source_api']}: "
                  f"{(meta['title'] or '?')[:70]} ({meta.get('year')})")
    title = a.title or (meta or {}).get("title")
    if title:
        g.add((s, RDFS.label, Literal(title, lang="en")))
    if a.doi:
        g.add((s, AIPROV.doi, Literal("https://doi.org/" +
              a.doi.removeprefix("https://doi.org/").removeprefix("doi:"),
              datatype=XSD.anyURI)))
    if a.url:
        g.add((s, DCT.source, URIRef(a.url)))
    if meta:
        if meta.get("year"):
            g.add((s, DCT.date, Literal(str(meta["year"]))))
        if meta.get("container"):
            g.add((s, DCT.isPartOf, Literal(meta["container"])))
    _set_state(g, a.base, s, state)
    if a.verify:
        act = ns(a.base, "activity")[f"verify-src-{a.id}"]
        g.add((act, RDF.type, AIPROV.AuditPass))
        g.add((act, RDFS.label, Literal(
            f"DOI verification of src:{a.id} via "
            f"{(meta or {}).get('source_api', 'crossref/openalex')} -> {state}", lang="en")))
        g.add((act, PROV.endedAtTime, now()))
        g.add((act, PROV.used, s))
        if a.agent:
            g.add((act, PROV.wasAssociatedWith, ns(a.base, "agent")[a.agent]))
    save(g)
    print(f"src:{a.id} registered at rung '{state}'")


def cmd_promote(a) -> None:
    g = load()
    _require_registered(g, a.base, a.agent)
    node = None
    for kind in ("source", "claim"):
        cand = ns(a.base, kind)[a.id]
        if (cand, None, None) in g:
            node = cand
            break
    if node is None:
        sys.exit(f"no source or claim with id '{a.id}' in graph")
    cur = "unverified"
    for st in g.objects(node, AIPROV.verificationState):
        cur = canon_rung(str(st).rsplit("/", 1)[-1])
    a.to = canon_rung(a.to)
    if a.to not in LADDER:
        sys.exit(f"unknown rung '{a.to}'; ladder: {' -> '.join(LADDER)}")
    if cur not in LADDER:
        sys.exit(f"'{a.id}' is at '{cur}', which is not on the ladder ({' -> '.join(LADDER)}); "
                 f"moving it is a graph repair, not a promotion")
    if LADDER.index(a.to) <= LADDER.index(cur):
        sys.exit(f"'{a.to}' is not above current rung '{cur}' — "
                 f"demotions/no-ops are graph repairs, not promotions")
    agent = ns(a.base, "agent")[a.agent]
    _refuse_human_only(g, a.base, a.to, a.agent, "promote", a.id, getattr(a, "record_refusals", False))
    _set_state(g, a.base, node, a.to)
    act = ns(a.base, "activity")[f"promote-{a.id}-{a.to}"]
    g.add((act, RDF.type, AIPROV.AuditPass))
    g.add((act, RDFS.label, Literal(
        f"Promotion of {a.id}: {cur} -> {a.to}" +
        (f" ({a.note})" if a.note else ""), lang="en")))
    g.add((act, PROV.endedAtTime, now()))
    g.add((act, PROV.used, node))
    g.add((act, PROV.wasAssociatedWith, agent))
    save(g)
    print(f"{a.id}: {cur} -> {a.to} (logged as AuditPass, agent:{a.agent})")


def _rung_rank(state) -> int:
    name = canon_rung(str(state).rsplit("/", 1)[-1])
    return LADDER.index(name) if name in LADDER else -1


def _fail_lines(g: Graph) -> set:
    """The failures of g as comparable lines: each [FAIL] line plus the evidence line of every offending
    node (and of unwitnessed human-only rungs, a WARN in validate that merge treats as a failure), so
    that fixing one failure while adding another of the same kind is still a regression."""
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        validate_graph(g)
    return {ln for ln in buf.getvalue().splitlines() if ln.startswith("[FAIL]") or ln.startswith("   ↳")}


def cmd_merge(a) -> None:
    """Union shard graphs into the main graph (append-only). A shard is refused if it is unreadable, has
    blank nodes, edits the plan or timing of an orchestration already in the main graph, retypes an existing
    node, demotes a node below its current rung, or introduces any validation failure (including a
    human-only rung without a human promotion). Accepted shards are merged; ladder states are normalised to
    the highest rung per node, states outside the ladder (e.g. contested) are kept."""
    from rdflib import BNode
    g = load()
    if any(isinstance(x, BNode) for t in g for x in t):
        sys.exit("the main graph contains blank nodes; merge cannot compare shards against it (skolemise them first)")
    frozen_props = (AIPROV.plannedAgent, AIPROV.plannedRole, AIPROV.plannedBinding, PROV.endedAtTime)
    base_fail = _fail_lines(g)
    main_rank = {n: max(_rung_rank(s_) for s_ in g.objects(n, AIPROV.verificationState))
                 for n in set(g.subjects(AIPROV.verificationState, None))}  # before this call: order-independent
    existing = set(g.subjects(RDF.type, None))
    orchestrations = set(g.subjects(RDF.type, AIPROV.Orchestration))
    merged, rejected = [], []
    for path in a.from_:
        try:
            shard = Graph(); shard.parse(path, format="turtle")
        except Exception as e:  # noqa: BLE001 - any unreadable file is a rejected shard, not a crash
            rejected.append((path, f"unreadable shard ({type(e).__name__})")); continue
        new = [t for t in shard if t not in g]
        why = None
        if any(isinstance(x, BNode) for t in new for x in t):
            why = "blank nodes are not merged"
        for s_, p_, o_ in new:
            if why:
                break
            name = str(s_).rsplit("/", 1)[-1]
            if s_ in orchestrations and (p_ in frozen_props or (p_ == PROV.wasInformedBy and o_ == s_)):
                why = f"edits the frozen plan or timing of {name}"
            elif p_ == RDF.type and s_ in existing:
                why = f"retypes the existing node {name}"
            elif p_ == AIPROV.verificationState and 0 <= _rung_rank(o_) < main_rank.get(s_, -1):
                why = f"demotes {name} below its current rung (a repair belongs in the main graph, not in a merge)"
        if why is None:
            cand = Graph(); cand += g
            for prefix, uri in g.namespaces():  # the validate queries use these prefixes
                cand.bind(prefix, uri)
            for t in new:
                cand.add(t)
            added = _fail_lines(cand) - base_fail
            if added:
                why = "validation: " + "; ".join(sorted(x.strip() for x in added))
        if why:
            rejected.append((path, why)); continue
        for t in new:
            g.add(t)
        merged.append((path, len(new)))
    for node in set(g.subjects(AIPROV.verificationState, None)):
        ladder = [st for st in g.objects(node, AIPROV.verificationState) if _rung_rank(st) >= 0]
        if len(ladder) > 1:
            keep = max(ladder, key=_rung_rank)
            for st in ladder:
                if st != keep:
                    g.remove((node, AIPROV.verificationState, st))
    unresolved = _external_refs(g)
    if unresolved and merged:
        print(f"[WARN] external references not resolved by the merged graphs: {len(unresolved)}")
        for n in unresolved:
            print("   ↳", n)
    if merged and not a.dry_run:
        save(g)
    for path, n in merged:
        print(f"merged {path}: {n} new triples")
    for path, why in rejected:
        print(f"REJECTED {path}: {why}")
    if a.dry_run:
        print("dry run: nothing written")
    sys.exit(1 if rejected else 0)


def cmd_extract(a) -> None:
    import collections
    from rdflib import URIRef
    src = pathlib.Path(a.graph) if a.graph else GRAPH
    g = Graph(); g.parse(src, format="turtle")
    both = (AIPROV, FAIR2R)
    seeds = set()
    for t in a.seed_types:
        for n in both:
            seeds |= set(g.subjects(RDF.type, n[t]))
    if not seeds:
        sys.exit(f"no seed entities of types {a.seed_types} found in {src}")
    excl = set()
    for t in a.exclude_kinds or []:
        for n in both:
            excl |= set(g.subjects(RDF.type, n[t]))
    follow = [PROV.wasGeneratedBy, PROV.wasDerivedFrom, PROV.wasAttributedTo,
              PROV.specializationOf, PROV.wasAssociatedWith, PROV.used,
              PROV.wasInformedBy, PROV.hadPlan]
    for n in both:
        follow += [n.transcript, n.repairs]
    keep, q = set(seeds), collections.deque(seeds)
    while q:
        node = q.popleft()
        nbrs = {o for pr in follow for o in g.objects(node, pr)
                if isinstance(o, URIRef)}
        for n in both:
            nbrs |= set(g.subjects(n.repairs, node))
        for m in nbrs - excl:
            if m not in keep:
                keep.add(m); q.append(m)
    out = Graph()
    for pfx, u in g.namespaces():
        out.bind(pfx, u)
    for s_, p_, o_ in g:
        if s_ in keep and (isinstance(o_, Literal) or o_ in keep or p_ == RDF.type
                           or "verification" in str(o_).lower()
                           or str(p_).endswith("source")):
            out.add((s_, p_, o_))
    out.serialize(a.out, format="turtle")
    print(f"extract: {len(seeds)} seeds -> {len(keep)} nodes, "
          f"{len(out)}/{len(g)} triples -> {a.out}")
    if a.dashboard:
        import json
        from aiprov import build_dashboard as bd
        data = bd.extract(pathlib.Path(a.out))
        html = bd.HTML.replace("__DATA__",
                               json.dumps(data).replace("</", "<\\/"))
        pathlib.Path(a.dashboard).write_text(html, encoding="utf-8")
        print(f"dashboard -> {a.dashboard} "
              f"({len(data['nodes'])} nodes, {len(data['edges'])} edges)")


def main() -> None:
    p = argparse.ArgumentParser(prog="provlog", description=__doc__)
    p.add_argument("--base", default=DEFAULT_BASE, help="instance-IRI base")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("--force", action="store_true")

    s = sub.add_parser("agent")
    s.add_argument("--id", required=True); s.add_argument("--type", choices=["ai", "human", "tool"], required=True)
    for f in ["name", "model", "model_version", "provider", "endpoint", "context_window",
              "knowledge_cutoff", "orcid", "affiliation"]:
        s.add_argument("--" + f.replace("_", "-"), dest=f)
    s.add_argument("--acted-on-behalf-of", dest="acted_on_behalf_of",
                   help="agent id this agent acts for (prov:actedOnBehalfOf), e.g. orchestrator")
    s.add_argument("--by", help="agent id that registers a person (default: $PROV_ACTOR); recorded as aiprov:registeredBy")

    s = sub.add_parser("log")
    s.add_argument("--activity", required=True); s.add_argument("--label")
    s.add_argument("--pass", dest="pass_", choices=["authoring", "audit", "build", "repair", "auxiliary"], default="authoring")
    s.add_argument("--agent"); s.add_argument("--started")
    s.add_argument("--ended", help="end of the work; defaults to now, which is the moment of recording, "
                                   "not necessarily the moment the work finished")
    s.add_argument("--commit")
    s.add_argument("--total-tokens", dest="total_tokens")
    for key, _, _ in ACT_ATTRS:
        s.add_argument("--" + key.replace("_", "-"), dest=key)
    s.add_argument("--tool", action="append"); s.add_argument("--prompt-file", dest="prompt_file")
    s.add_argument("--transcript"); s.add_argument("--generated", action="append")
    s.add_argument("--used", action="append")
    s.add_argument("--used-decision", dest="used_decision", action="append",
                   help="id of a decision (see `provlog decision`) this activity used, e.g. the one that authorised it; repeatable")
    s.add_argument("--used-message", dest="used_message", action="append",
                   help="id of a message (see `provlog message`) this activity used; repeatable")
    s.add_argument("--orchestration", action="store_true",
                   help="root of a multi-agent run; log it before any sub-agent starts")
    s.add_argument("--planned-role", dest="planned_role", action="append")
    s.add_argument("--planned-agent", dest="planned_agent", action="append",
                   help="agent id, or ID:ROLE to bind the agent to one role; must be registered already")
    s.add_argument("--informed-by", dest="informed_by", help="activity id (prov:wasInformedBy)")
    s.add_argument("--used-external", dest="used_external", action="append", metavar="IRI",
                   help="IRI of an entity that another provenance graph defines (prov:used); needs --defined-in; "
                        "only the IRI, an optional hash and commit are written, never a path or label; repeatable")
    s.add_argument("--informed-by-external", dest="informed_by_external", action="append", metavar="IRI",
                   help="IRI of an activity that another provenance graph defines (prov:wasInformedBy); needs --defined-in")
    s.add_argument("--defined-in", dest="defined_in", metavar="GRAPH_IRI",
                   help="IRI of the provenance graph that defines the external node (rdfs:isDefinedBy)")
    s.add_argument("--external-hash", dest="external_hash", metavar="sha256:HEX",
                   help="content hash of the external entity (optional; a hash of restricted material is a weak disclosure)")
    s.add_argument("--external-commit", dest="external_commit", metavar="SHA", help="commit of the external entity (optional)")
    s.add_argument("--role", help="role of this sub-activity within the orchestration")
    s.add_argument("--model-role", dest="model_role",
                   help="what the model did within one answer: answer, draft, revise, judge, route (or your own)")
    s.add_argument("--fallback-of", dest="fallback_of", help="activity id this activity replaces after a failure")
    s.add_argument("--fallback-reason", dest="fallback_reason", choices=FALLBACK_REASONS,
                   help="why the fallback happened (needs --fallback-of)")
    s.add_argument("--routed-by", dest="routed_by", help="id of the routing rule (a prov:Plan) that chose this model")
    s.add_argument("--judges", help="path of the answer a judge activity scored (needs --score)")
    s.add_argument("--score", help="the value the judge gave (needs --judges)")
    s.add_argument("--session", help="session id: the activity is part of this session (created on first mention)")
    s.add_argument("--session-type", dest="session_type",
                   help=f"kind of session: {', '.join(SESSION_TYPES)}, or the IRI of your own concept")
    s.add_argument("--session-outcome", dest="session_outcome", choices=SESSION_OUTCOMES,
                   help="how the session ended, as the harness reports it")
    s.add_argument("--session-started", dest="session_started", help="start of the session (ISO 8601)")
    s.add_argument("--session-ended", dest="session_ended", help="end of the session (ISO 8601)")
    s.add_argument("--capture-path", dest="capture_path", choices=CAPTURE_PATHS,
                   help="how this record came to be: " + ", ".join(CAPTURE_PATHS) + " (absent = unknown)")
    s.add_argument("--recorded-by", dest="recorded_by",
                   help="registered agent that wrote the record, when it is not the acting agent")
    s.add_argument("--recorded-from", dest="recorded_from",
                   help="path of the source a record was written from (a summary, a transcript, a commit)")
    s.add_argument("--harness", help="id of the harness this activity ran under (see `provlog harness`)")
    s.add_argument("--model-variant", dest="model_variant",
                   help="reasoning variant in force for this activity (for example low, max); it can change per request")
    s.add_argument("--model-unknown-reason", dest="model_unknown_reason",
                   help="why the model is not known (for example: not reported by the harness), instead of a guess")

    s = sub.add_parser("harness", help="register the harness an activity ran under")
    s.add_argument("--id", required=True)
    s.add_argument("--kind", required=True, help=f"{', '.join(HARNESS_KINDS)}, or the IRI of your own concept")
    s.add_argument("--version", help="version of the harness")
    s.add_argument("--config-file", dest="config_file",
                   help=f"configuration to hash ({CONFIG_NORMALISER}: secrets removed, URLs hashed, list order kept); never stored")
    s.add_argument("--name")

    s = sub.add_parser("claim")
    s.add_argument("--id", required=True); s.add_argument("--text", required=True)
    s.add_argument("--parent", required=True); s.add_argument("--agent", required=True)
    s.add_argument("--state", default="unverified")
    s.add_argument("--record-refusals", dest="record_refusals", action="store_true",
                   help="write a refused human-only step to the graph as an aiprov:Refusal (default: the graph stays unchanged)")

    s = sub.add_parser("message", help="record one message of an agent in a channel")
    s.add_argument("--id", required=True); s.add_argument("--channel", required=True)
    s.add_argument("--agent", required=True, help="registered sender")
    s.add_argument("--text", help="the text; only its sha256 is stored unless --keep-text is given")
    s.add_argument("--content-hash", dest="content_hash", help="sha256:<hex> of a text that is not passed in")
    s.add_argument("--keep-text", dest="keep_text", action="store_true",
                   help="also store the text (only where the data class of the channel allows it)")
    s.add_argument("--reply-to", dest="reply_to", help="id of the message this one replies to (same graph)")
    s.add_argument("--refers-to", dest="refers_to", action="append", help="IRI of an issue, pull request or commit")
    s.add_argument("--sent-at", dest="sent_at", help="when the message was sent (ISO 8601); omitted when unknown")
    s.add_argument("--platform"); s.add_argument("--channel-name", dest="channel_name")
    s.add_argument("--channel-class", dest="channel_class", choices=DATA_CLASSES,
                   help="data class of the channel (write-once)")

    s = sub.add_parser("decision", help="record a decision: the question, its options, the recommendation, who chose what")
    s.add_argument("action", choices=["open", "decide", "supersede"])
    s.add_argument("--id", required=True)
    s.add_argument("--agent", help="registered agent: the asker (open) or the decider (decide)")
    s.add_argument("--question", help="open: the question; only its sha256 is stored unless --keep-text")
    s.add_argument("--option", action="append", metavar="ID=TEXT", help="open: an option, at least two; repeatable")
    s.add_argument("--recommend", metavar="OPTION_ID", help="open: the recommended option")
    s.add_argument("--keep-text", dest="keep_text", action="store_true",
                   help="open: also store the question and option texts (only for --data-class public, untrusted or internal)")
    s.add_argument("--data-class", dest="data_class", choices=DATA_CLASSES, help="open: data class of the question text")
    s.add_argument("--asked-in", dest="asked_in", help="open: IRI of the issue, pull request or message where it was asked")
    s.add_argument("--choose", metavar="OPTION_ID", help="decide: the option chosen")
    s.add_argument("--state", choices=["provisional", "done"], default="done",
                   help="decide: provisional (an AI may set it) or done (a registered human only)")
    s.add_argument("--decided-in", dest="decided_in", help="decide: IRI of the place of the decision")
    s.add_argument("--decided-at", dest="decided_at", help="decide: when it was decided (ISO 8601); default now")
    s.add_argument("--old", help="supersede: the decision that --id replaces")

    s = sub.add_parser("bulk", help="bulk telemetry tier: a hash-chained JSONL file, its head anchored in the graph")
    s.add_argument("action", choices=["append", "verify", "anchor"])
    s.add_argument("--file", required=True, help="the JSONL file of the chain")
    s.add_argument("--data", help="append: one JSON object")
    s.add_argument("--data-file", dest="data_file", help="append: a file holding one JSON object")
    s.add_argument("--id", help="anchor: id of the chain anchor in the graph")
    s.add_argument("--agent", help="anchor: registered agent that anchors the head")
    s.add_argument("--upto", type=int, help="anchor: anchor the first N records only (default all)")
    s.add_argument("--anchor", help="verify: also check the file against this anchor of the graph")

    sub.add_parser("validate"); sub.add_parser("report")

    s = sub.add_parser("migrate", help="bring the graph to the schema version of this provlog")
    s.add_argument("--dry-run", action="store_true", help="print what would change; write nothing")
    s.add_argument("--to", metavar="VERSION", help=f"target version (default {SCHEMA_VERSION})")
    s.add_argument("--agent", help="registered agent that ran the migration")

    s = sub.add_parser("merge", help="union shard graphs into the main graph")
    s.add_argument("--from", dest="from_", nargs="+", required=True, metavar="SHARD.ttl")
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("search")
    s.add_argument("--query", required=True)
    s.add_argument("--rows", type=int, default=5)
    s.add_argument("--backend", action="append",
                   choices=["crossref", "openalex", "arxiv", "datacite"],
                   help="repeatable; default crossref + openalex")

    s = sub.add_parser("source")
    s.add_argument("--id", required=True)
    s.add_argument("--doi"); s.add_argument("--url"); s.add_argument("--title")
    s.add_argument("--state", choices=LADDER + sorted(RUNG_ALIASES))
    s.add_argument("--verify", action="store_true",
                   help="resolve the DOI via Crossref/OpenAlex and promote to retrieved")
    s.add_argument("--agent", help="agent performing the verification")
    s.add_argument("--record-refusals", dest="record_refusals", action="store_true",
                   help="write a refused human-only step to the graph as an aiprov:Refusal (default: the graph stays unchanged)")

    s = sub.add_parser("promote")
    s.add_argument("--id", required=True, help="source or claim id")
    s.add_argument("--to", required=True, help="target rung")
    s.add_argument("--agent", required=True)
    s.add_argument("--note")
    s.add_argument("--record-refusals", dest="record_refusals", action="store_true",
                   help="write a refused human-only step to the graph as an aiprov:Refusal (default: the graph stays unchanged)")

    s = sub.add_parser("extract")
    s.add_argument("--graph", help="input TTL (default provenance.ttl)")
    s.add_argument("--seed-types", nargs="+", required=True,
                   help="entity classes to seed from, e.g. Manuscript Section Figure Claim")
    s.add_argument("--exclude-kinds", nargs="+",
                   help="classes never pulled into the closure, e.g. Slidedeck Poster")
    s.add_argument("-o", "--out", default="provenance-extract.ttl")
    s.add_argument("--dashboard", help="also render an HTML dashboard of the extract")

    a = p.parse_args()
    if a.cmd == "bulk" and a.action == "anchor" and not (a.id and a.agent):
        p.error("bulk anchor needs --id and --agent")
    {"init": cmd_init, "agent": cmd_agent, "harness": cmd_harness, "log": cmd_log,
     "claim": cmd_claim, "message": cmd_message, "decision": cmd_decision, "bulk": cmd_bulk, "validate": cmd_validate, "merge": cmd_merge, "report": cmd_report,
     "extract": cmd_extract, "migrate": cmd_migrate, "source": cmd_source, "promote": cmd_promote, "search": cmd_search}[a.cmd](a)


if __name__ == "__main__":
    main()
