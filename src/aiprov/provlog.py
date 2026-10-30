#!/usr/bin/env python3
"""provlog — append-only AI provenance logger over PROV-O (aiprov: profile).

Commands:
  init                       Seed provenance.ttl from the aiprov schema.
  agent   --id --type ...    Register a human/AI/tool agent with attributes.
  log     --activity ...     Record an activity with full inference telemetry
                             (tokens, cost, model, session, tools, prompt hash)
                             and optionally the entities it generated/used.
  claim   --id ...           Add a claim bound to a parent activity + agent.
  merge   --from SHARD...    Union per-agent shard graphs into the main graph; refuses shards that
                             edit a frozen plan or add validation failures.
  (multi-agent) log --orchestration --planned-role/--planned-agent, then sub-activities with
                             --informed-by/--role; agent --acted-on-behalf-of.
  validate                   Conformance: parentless claims, AI-granted
                             human-only verification rungs, missing attribution.
  report                     Totals: tokens, cost, activities per agent, rungs.
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
import argparse, datetime, hashlib, pathlib, re, sys
from rdflib import Graph, Namespace, Literal, URIRef, RDF, RDFS, XSD

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
    print(f"Seeded {GRAPH} ({len(g)} triples, base {a.base})")


def cmd_agent(a) -> None:
    g = load()
    s = ns(a.base, "agent")[a.id]
    cls = {"ai": AIPROV.AIAgent, "human": AIPROV.HumanAgent, "tool": AIPROV.ToolAgent}[a.type]
    g.add((s, RDF.type, cls))
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


def cmd_log(a) -> None:
    g = load()
    act = ns(a.base, "activity")[a.activity]
    cls = {"authoring": AIPROV.AuthoringPass, "audit": AIPROV.AuditPass,
           "build": AIPROV.Build, "repair": AIPROV.Repair}.get(a.pass_, PROV.Activity)
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
    _link_session(g, a, act)
    if a.label:
        g.add((act, RDFS.label, Literal(a.label, lang="en")))
    g.add((act, PROV.endedAtTime, now()))
    if a.started:
        g.add((act, PROV.startedAtTime, Literal(a.started, datatype=XSD.dateTime)))
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
    for path in a.used or []:
        e = ns(a.base, "source")[pathlib.Path(path).name.replace(".", "-")]
        g.add((e, RDF.type, AIPROV.Source))
        g.add((e, AIPROV.filePath, Literal(path)))
        g.add((act, PROV.used, e))
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


def _refuse_human_only(g: Graph, base: str, state: "str | None", agent: "str | None") -> None:
    """Exit with the refusal of `promote` when a human-only rung is set by an agent that is not a registered HumanAgent."""
    if state and canon_rung(state) in HUMAN_ONLY and not _is_human(g, base, agent):
        why = (f"agent:{agent} is not a registered HumanAgent" if agent
               else "no --agent was given, and a registered HumanAgent is required")
        sys.exit(f"REFUSED: rung '{canon_rung(state)}' is human-only; {why}. An AI must never grant this rung.")


def _clean_state(state: str) -> str:
    """A state as one lower-case token; any other form is read as a different state by validate and report."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", state):
        sys.exit(f"invalid state '{state}': use one token of letters, digits and hyphens")
    return state.lower()


def cmd_claim(a) -> None:
    g = load()
    a.state = _clean_state(a.state)
    _require_registered(g, a.base, a.agent)
    _refuse_human_only(g, a.base, a.state, a.agent)
    c = ns(a.base, "claim")[a.id]
    g.add((c, RDF.type, AIPROV.Claim))
    g.add((c, RDFS.label, Literal(a.text, lang="en")))
    g.add((c, PROV.wasGeneratedBy, ns(a.base, "activity")[a.parent]))
    g.add((c, PROV.wasAttributedTo, ns(a.base, "agent")[a.agent]))
    g.add((c, AIPROV.verificationState, ns(a.base, "verification")[a.state]))
    save(g)
    print(f"claim:{a.id} added (state {a.state})")


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
    # An agent that is named but was never registered carries no type, model or name (issue 21).
    unreg = list(g.query("""SELECT DISTINCT ?ag WHERE {
            { ?x prov:wasAssociatedWith ?ag } UNION { ?x prov:wasAttributedTo ?ag }
            FILTER NOT EXISTS { ?ag a aiprov:AIAgent } FILTER NOT EXISTS { ?ag a aiprov:HumanAgent }
            FILTER NOT EXISTS { ?ag a aiprov:ToolAgent } }"""))
    print(f"[{'FAIL' if unreg else ' OK '}] agents referenced but not registered: {len(unreg)}")
    fail += len(unreg)
    # Orchestration (multi-agent runs): delegation links must resolve and obey the declared plan.
    dangling = list(g.query("""SELECT ?a ?p WHERE { ?a prov:wasInformedBy ?p .
            FILTER NOT EXISTS { ?p prov:endedAtTime ?t } }"""))
    print(f"[{'FAIL' if dangling else ' OK '}] wasInformedBy targets that are not logged activities: {len(dangling)}")
    fail += len(dangling)
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
    # Sessions: an activity that says it is part of something must name a session of this graph.
    badpart = list(g.query("""SELECT ?a ?s WHERE { ?a dcterms:isPartOf ?s ; prov:endedAtTime ?t .
            FILTER NOT EXISTS { ?s a aiprov:Session } }"""))
    print(f"[{'FAIL' if badpart else ' OK '}] activities that are part of something that is not a session: {len(badpart)}")
    fail += len(badpart)
    for kind, rows in (("parentless claim", orphans), ("unattributed claim", unattr),
                       ("human-only rung granted by an AI agent", bad), ("source without reference", noref),
                       ("human-only rung without human promotion", unwit),
                       ("agent referenced but not registered", unreg),
                       ("wasInformedBy target not logged", dangling), ("outside the plan", unplanned),
                       ("orchestration logged twice", reclosed), ("logged before its orchestration", early),
                       ("part of a non-session", badpart)):
        for row in rows:
            print("   ↳", kind + ":", row[0])
    return fail


def cmd_validate(a) -> None:
    sys.exit(1 if validate_graph(load()) else 0)


def cmd_report(a) -> None:
    g = load()
    def total(prop):
        return sum(int(o) for _, _, o in g.triples((None, prop, None)))
    print("== aiprov report ==")
    print(f"triples:            {len(g)}")
    sessions = set(g.subjects(RDF.type, AIPROV.Session))
    print(f"activities:         {len(set(g.subjects(PROV.endedAtTime, None)) - sessions)}")
    print(f"claims:             {len(set(g.subjects(RDF.type, AIPROV.Claim)))}")
    print(f"input tokens:       {total(AIPROV.inputTokens)}")
    print(f"output tokens:      {total(AIPROV.outputTokens)}")
    print(f"cache read tokens:  {total(AIPROV.cacheReadTokens)}")
    print(f"total tokens:       {total(AIPROV.totalTokens)}")
    cost = sum(float(o) for _, _, o in g.triples((None, AIPROV.cost, None)))
    cur = {str(o) for _, _, o in g.triples((None, AIPROV.costCurrency, None))} or {"?"}
    print(f"cost:               {cost:.4f} {'/'.join(sorted(cur))}")
    print("-- tokens per agent --")
    q = """SELECT ?ag (SUM(?t) AS ?tok) (COUNT(DISTINCT ?act) AS ?n) WHERE {
            ?act prov:wasAssociatedWith ?ag ; aiprov:totalTokens ?t }
           GROUP BY ?ag ORDER BY DESC(?tok)"""
    for ag, tok, n in g.query(q):
        print(f"   {str(ag).rsplit('/',1)[-1]:24s} {int(tok):>10} tok  {int(n)} activities")
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
    _refuse_human_only(g, a.base, state, a.agent)
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
    _refuse_human_only(g, a.base, a.to, a.agent)
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

    s = sub.add_parser("log")
    s.add_argument("--activity", required=True); s.add_argument("--label")
    s.add_argument("--pass", dest="pass_", choices=["authoring", "audit", "build", "repair"], default="authoring")
    s.add_argument("--agent"); s.add_argument("--started"); s.add_argument("--commit")
    s.add_argument("--total-tokens", dest="total_tokens")
    for key, _, _ in ACT_ATTRS:
        s.add_argument("--" + key.replace("_", "-"), dest=key)
    s.add_argument("--tool", action="append"); s.add_argument("--prompt-file", dest="prompt_file")
    s.add_argument("--transcript"); s.add_argument("--generated", action="append")
    s.add_argument("--used", action="append")
    s.add_argument("--orchestration", action="store_true",
                   help="root of a multi-agent run; log it before any sub-agent starts")
    s.add_argument("--planned-role", dest="planned_role", action="append")
    s.add_argument("--planned-agent", dest="planned_agent", action="append",
                   help="agent id, or ID:ROLE to bind the agent to one role; must be registered already")
    s.add_argument("--informed-by", dest="informed_by", help="activity id (prov:wasInformedBy)")
    s.add_argument("--role", help="role of this sub-activity within the orchestration")
    s.add_argument("--session", help="session id: the activity is part of this session (created on first mention)")
    s.add_argument("--session-type", dest="session_type",
                   help=f"kind of session: {', '.join(SESSION_TYPES)}, or the IRI of your own concept")
    s.add_argument("--session-outcome", dest="session_outcome", choices=SESSION_OUTCOMES,
                   help="how the session ended, as the harness reports it")
    s.add_argument("--session-started", dest="session_started", help="start of the session (ISO 8601)")
    s.add_argument("--session-ended", dest="session_ended", help="end of the session (ISO 8601)")

    s = sub.add_parser("claim")
    s.add_argument("--id", required=True); s.add_argument("--text", required=True)
    s.add_argument("--parent", required=True); s.add_argument("--agent", required=True)
    s.add_argument("--state", default="unverified")

    sub.add_parser("validate"); sub.add_parser("report")

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

    s = sub.add_parser("promote")
    s.add_argument("--id", required=True, help="source or claim id")
    s.add_argument("--to", required=True, help="target rung")
    s.add_argument("--agent", required=True)
    s.add_argument("--note")

    s = sub.add_parser("extract")
    s.add_argument("--graph", help="input TTL (default provenance.ttl)")
    s.add_argument("--seed-types", nargs="+", required=True,
                   help="entity classes to seed from, e.g. Manuscript Section Figure Claim")
    s.add_argument("--exclude-kinds", nargs="+",
                   help="classes never pulled into the closure, e.g. Slidedeck Poster")
    s.add_argument("-o", "--out", default="provenance-extract.ttl")
    s.add_argument("--dashboard", help="also render an HTML dashboard of the extract")

    a = p.parse_args()
    {"init": cmd_init, "agent": cmd_agent, "log": cmd_log,
     "claim": cmd_claim, "validate": cmd_validate, "merge": cmd_merge, "report": cmd_report,
     "extract": cmd_extract, "source": cmd_source, "promote": cmd_promote, "search": cmd_search}[a.cmd](a)


if __name__ == "__main__":
    main()
