"""Composite claims: premises, composition, computed effective rung (issue 36)."""
import subprocess, sys

BASE = "https://example.org/prov/"


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", BASE, *args], cwd=cwd,
                          capture_output=True, text=True)


def ok(args, cwd):
    r = run(args, cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def setup(tmp_path):
    ok(["init"], tmp_path)
    ok(["agent", "--id", "m1", "--type", "ai", "--model", "m-1"], tmp_path)
    ok(["agent", "--id", "alex", "--type", "human", "--name", "Alex Example"], tmp_path)
    ok(["log", "--activity", "act", "--pass", "authoring", "--agent", "m1"], tmp_path)


def claim(tmp_path, cid, state="unverified", *extra):
    return run(["claim", "--id", cid, "--text", f"text {cid}", "--parent", "act", "--agent", "m1",
                "--state", state, *extra], tmp_path)


def premises(tmp_path, states):
    setup(tmp_path)
    for i, s in enumerate(states, 1):
        assert claim(tmp_path, f"p{i}", s).returncode == 0
    return [f"p{i}" for i in range(1, len(states) + 1)]


def prem_args(ids):
    return [x for i in ids for x in ("--premise", i)]


def effective(tmp_path, cid):
    for line in ok(["report"], tmp_path).stdout.splitlines():
        if line.strip().startswith(cid + " "):
            return line
    raise AssertionError("no composite line for " + cid)


def test_allof_is_the_weakest_link(tmp_path):
    ids = premises(tmp_path, ["unverified", "ai-confirmed"])
    ok(["claim", "--id", "c", "--text", "t", "--parent", "act", "--agent", "m1",
        *prem_args(ids), "--composition", "all"], tmp_path)
    assert "effective unverified" in effective(tmp_path, "c")
    assert ok(["validate"], tmp_path).returncode == 0


def test_anyof_is_the_best_premise(tmp_path):
    ids = premises(tmp_path, ["unverified", "ai-confirmed"])
    ok(["claim", "--id", "c", "--text", "t", "--parent", "act", "--agent", "m1", "--state", "ai-confirmed",
        *prem_args(ids), "--composition", "any"], tmp_path)
    assert "effective ai-confirmed" in effective(tmp_path, "c")


def test_atleast_picks_the_kth_best(tmp_path):
    ids = premises(tmp_path, ["unverified", "ai-confirmed", "reference-resolved"])
    ok(["claim", "--id", "c", "--text", "t", "--parent", "act", "--agent", "m1", "--state", "reference-resolved",
        *prem_args(ids), "--composition", "atleast:2"], tmp_path)
    assert "effective reference-resolved" in effective(tmp_path, "c")


def test_refutation_for_the_three_compositions(tmp_path):
    ids = premises(tmp_path, ["contested", "ai-confirmed"])
    for cid, comp, state, expect in (("ca", "all", "unverified", "refuted"), ("cb", "any", "ai-confirmed", "ai-confirmed"),
                                     ("cc", "atleast:2", "unverified", "refuted")):
        ok(["claim", "--id", cid, "--text", "t", "--parent", "act", "--agent", "m1", "--state", state,
            *prem_args(ids), "--composition", comp], tmp_path)
        assert f"effective {expect}" in effective(tmp_path, cid), cid


def test_composite_of_composite_and_stated_rung_above_effective_is_refused(tmp_path):
    ids = premises(tmp_path, ["unverified", "ai-confirmed"])
    ok(["claim", "--id", "inner", "--text", "t", "--parent", "act", "--agent", "m1",
        *prem_args(ids), "--composition", "any"], tmp_path)
    r = run(["claim", "--id", "outer", "--text", "t", "--parent", "act", "--agent", "m1", "--state", "ai-confirmed",
             "--premise", "inner", "--premise", "p1", "--composition", "all"], tmp_path)
    assert r.returncode != 0 and "effective rung" in r.stdout + r.stderr
    assert "outer" not in (tmp_path / "provenance.ttl").read_text(encoding="utf-8")


def test_input_checks(tmp_path):
    ids = premises(tmp_path, ["unverified", "unverified"])
    assert claim(tmp_path, "x", "unverified", "--premise", "nope").returncode != 0
    assert claim(tmp_path, "x", "unverified", *prem_args(ids), "--composition", "atleast:3").returncode != 0
    assert claim(tmp_path, "x", "unverified", *prem_args(ids), "--composition", "some").returncode != 0
    assert claim(tmp_path, "x", "unverified", "--composition", "all").returncode != 0
    assert claim(tmp_path, "x", "unverified", "--premise", "x").returncode != 0


def test_promote_cannot_exceed_the_effective_rung(tmp_path):
    ids = premises(tmp_path, ["unverified", "ai-confirmed"])
    ok(["claim", "--id", "c", "--text", "t", "--parent", "act", "--agent", "m1",
        *prem_args(ids), "--composition", "all"], tmp_path)
    r = run(["promote", "--id", "c", "--to", "ai-confirmed", "--agent", "m1"], tmp_path)
    assert r.returncode != 0 and "effective rung" in r.stdout + r.stderr
    ok(["promote", "--id", "p1", "--to", "ai-confirmed", "--agent", "m1"], tmp_path)
    ok(["promote", "--id", "c", "--to", "ai-confirmed", "--agent", "m1"], tmp_path)
    assert "effective ai-confirmed" in effective(tmp_path, "c")


def test_validate_fails_on_cycle_bad_premise_and_bad_minpremises(tmp_path):
    ids = premises(tmp_path, ["unverified", "unverified"])
    ok(["claim", "--id", "c", "--text", "t", "--parent", "act", "--agent", "m1", *prem_args(ids)], tmp_path)
    ok(["claim", "--id", "d", "--text", "t", "--parent", "act", "--agent", "m1"], tmp_path)
    ttl = tmp_path / "provenance.ttl"
    base = ttl.read_text(encoding="utf-8")
    pre = "@prefix aiprov: <https://w3id.org/aiprov/ns#> .\n@prefix c: <https://example.org/prov/claim/> .\n"
    for extra, needle in (
            ("c:p1 aiprov:hasPremise c:c .\n", "[FAIL] premise cycles:"),
            ("c:c aiprov:hasPremise <https://example.org/prov/claim/ghost> .\n", "premises that are not claims: 1"),
            ("c:d aiprov:hasPremise c:p1 , c:p2 ; aiprov:composition aiprov:AtLeast ; aiprov:minPremises 5 .\n",
             "minPremises missing or above the number of premises: 1")):
        ttl.write_text(base + "\n" + pre + extra, encoding="utf-8")
        r = run(["validate"], tmp_path)
        assert r.returncode != 0 and needle in r.stdout, r.stdout


def test_legacy_promotion_before_premises_only_warns(tmp_path):
    ids = premises(tmp_path, ["unverified", "unverified"])
    ok(["claim", "--id", "c", "--text", "t", "--parent", "act", "--agent", "m1", "--state", "ai-confirmed"], tmp_path)
    ttl = tmp_path / "provenance.ttl"
    pre = "@prefix aiprov: <https://w3id.org/aiprov/ns#> .\n@prefix c: <https://example.org/prov/claim/> .\n"
    ttl.write_text(ttl.read_text(encoding="utf-8") + "\n" + pre +
                   "c:c aiprov:hasPremise c:p1 , c:p2 ; aiprov:composition aiprov:AllOf .\n", encoding="utf-8")
    r = run(["validate"], tmp_path)
    assert r.returncode == 0 and "[WARN] claims stated above their effective rung: 1" in r.stdout, r.stdout


def test_claims_without_premises_are_unchanged(tmp_path):
    setup(tmp_path)
    assert claim(tmp_path, "plain", "ai-confirmed").returncode == 0
    out = ok(["validate"], tmp_path).stdout
    assert "[ OK ] premise cycles: 0" in out and "composite claims" not in ok(["report"], tmp_path).stdout


def test_schema_declares_the_terms():
    from rdflib import Graph, URIRef
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for f in (root / "schema" / "aiprov-schema.ttl", root / "src" / "aiprov" / "aiprov-schema.ttl"):
        g = Graph(); g.parse(f, format="turtle")
        for t in ("hasPremise", "composition", "AllOf", "AnyOf", "AtLeast", "minPremises"):
            assert any(g.triples((URIRef("https://w3id.org/aiprov/ns#" + t), None, None))), (f.name, t)
