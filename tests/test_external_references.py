"""References across provenance graphs: external nodes carry IRI, hash and commit only (issue 37)."""
import hashlib
import subprocess
import sys

B_CODE, B_DATA, B_CI = ("https://example.org/prov/code/", "https://example.org/prov/data/", "https://example.org/prov/ci/")
G_CODE, G_DATA, G_CI = (B_CODE + "graph", B_DATA + "graph", B_CI + "graph")
CI_RUN = B_CI + "activity/gate-1"
DATA_ENT = B_DATA + "entity/restricted-config-yaml"
CODE_ENT = B_CODE + "entity/app-py"
H = "sha256:" + hashlib.sha256(b"x").hexdigest()


def run(base, args, cwd):
    return subprocess.run([sys.executable, "-m", "aiprov.provlog", "--base", base, *args], cwd=cwd,
                          capture_output=True, text=True, check=False)


def ok(base, args, cwd):
    r = run(base, args, cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def repo(tmp_path, name, base):
    d = tmp_path / name
    d.mkdir()
    ok(base, ["init"], d)
    ok(base, ["agent", "--id", "m1", "--type", "ai", "--model", "m-1"], d)
    return d


def three(tmp_path):
    data = repo(tmp_path, "data", B_DATA)
    (data / "restricted-config.yaml").write_text("secret: 1\n")
    ok(B_DATA, ["log", "--activity", "cfg-1", "--agent", "m1", "--pass", "authoring", "--generated", "restricted-config.yaml"], data)
    code = repo(tmp_path, "code", B_CODE)
    (code / "app.py").write_text("print(1)\n")
    ok(B_CODE, ["log", "--activity", "build-1", "--agent", "m1", "--pass", "authoring", "--generated", "app.py"], code)
    ci = repo(tmp_path, "ci", B_CI)
    ok(B_CI, ["log", "--activity", "gate-1", "--agent", "m1", "--pass", "build",
              "--used-external", DATA_ENT, "--defined-in", G_DATA, "--external-hash", H], ci)
    ok(B_CI, ["log", "--activity", "gate-2", "--agent", "m1", "--pass", "build",
              "--used-external", CODE_ENT, "--defined-in", G_CODE, "--external-commit", "abc1234"], ci)
    ok(B_CODE, ["log", "--activity", "fix-1", "--agent", "m1", "--pass", "repair",
                "--informed-by-external", CI_RUN, "--defined-in", G_CI], code)
    return code, data, ci


def test_each_graph_validates_alone_and_reports_external_references(tmp_path):
    code, data, ci = three(tmp_path)
    r = ok(B_CODE, ["validate"], code)
    assert "external references (nodes defined in another graph): 1" in r.stdout
    r = ok(B_CI, ["validate"], ci)
    assert "external references (nodes defined in another graph): 2" in r.stdout
    r = ok(B_DATA, ["validate"], data)
    assert "external references (nodes defined in another graph): 0" in r.stdout


def test_an_external_node_holds_only_iri_hash_and_commit(tmp_path):
    _code, _data, ci = three(tmp_path)
    text = (ci / "provenance.ttl").read_text()
    assert "restricted-config" in text and H in text and "abc1234" in text
    assert "restricted-config.yaml" not in text  # no file path of the restricted entity
    assert "secret" not in text
    from rdflib import RDF, Graph, URIRef
    g = Graph(); g.parse(ci / "provenance.ttl", format="turtle")
    node = URIRef(DATA_ENT)
    preds = {str(p) for p in g.predicates(node, None)}
    assert preds == {"http://www.w3.org/2000/01/rdf-schema#isDefinedBy", "https://w3id.org/aiprov/ns#contentHash"}
    assert (node, RDF.type, None) not in g


def test_an_unknown_informed_by_target_still_fails_without_the_marker(tmp_path):
    code = repo(tmp_path, "c", B_CODE)
    ok(B_CODE, ["log", "--activity", "a1", "--agent", "m1", "--pass", "authoring"], code)
    # hand-written dangling link without rdfs:isDefinedBy
    ttl = code / "provenance.ttl"
    ttl.write_text(ttl.read_text() + f"\n<{B_CODE}activity/a1> <http://www.w3.org/ns/prov#wasInformedBy> <{B_CI}activity/nowhere> .\n")
    r = run(B_CODE, ["validate"], code)
    assert r.returncode != 0 and "not logged activities: 1" in r.stdout


def test_refusals(tmp_path):
    code = repo(tmp_path, "c", B_CODE)
    base = ["log", "--activity", "a1", "--agent", "m1", "--pass", "authoring"]
    assert run(B_CODE, base + ["--used-external", DATA_ENT], code).returncode != 0            # no --defined-in
    assert run(B_CODE, base + ["--used-external", "not an iri", "--defined-in", G_DATA], code).returncode != 0
    assert run(B_CODE, base + ["--used-external", DATA_ENT, "--defined-in", G_DATA, "--external-hash", "abc"], code).returncode != 0
    assert run(B_CODE, base + ["--used-external", DATA_ENT, "--used-external", CODE_ENT, "--defined-in", G_DATA,
                               "--external-commit", "abc"], code).returncode != 0            # hash for two nodes
    assert run(B_CODE, base + ["--defined-in", G_DATA], code).returncode != 0                 # nothing to define
    assert not (code / "provenance.ttl").read_text().count("isDefinedBy")


def test_a_node_of_this_graph_is_not_external(tmp_path):
    code, _, _ = three(tmp_path)
    r = run(B_CODE, ["log", "--activity", "a2", "--agent", "m1", "--pass", "authoring",
                     "--used-external", CODE_ENT, "--defined-in", G_DATA], code)
    assert r.returncode != 0 and "defined in this graph" in r.stdout + r.stderr


def test_merge_resolves_external_references_or_warns(tmp_path):
    code, data, ci = three(tmp_path)
    def shutil_copy(src, name):
        dst = tmp_path / name
        dst.write_bytes((src / "provenance.ttl").read_bytes())
        return dst
    # the code graph alone leaves the reference to the CI run unresolved
    main = repo(tmp_path, "main", B_DATA)
    r = run(B_DATA, ["merge", "--from", str(shutil_copy(code, "code.ttl"))], main)
    assert "external references not resolved" in r.stdout, r.stdout + r.stderr
    # the CI graph defines the CI run, but still refers to the data and code entities: not resolved yet
    r = run(B_DATA, ["merge", "--from", str(shutil_copy(ci, "ci.ttl"))], main)
    assert "external references not resolved" in r.stdout, r.stdout + r.stderr
    assert "restricted-config-yaml" in r.stdout
    # with the graph that defines the data entity as well, every reference resolves
    r = run(B_DATA, ["merge", "--from", str(shutil_copy(data, "data.ttl"))], main)
    assert "external references not resolved" not in r.stdout, r.stdout + r.stderr


def test_validate_fails_an_external_node_with_a_path_or_a_label(tmp_path):
    code = repo(tmp_path, "c", B_CODE)
    ok(B_CODE, ["log", "--activity", "a1", "--agent", "m1", "--pass", "authoring",
                "--used-external", DATA_ENT, "--defined-in", G_DATA], code)
    assert "carry a file path or a label: 0" in ok(B_CODE, ["validate"], code).stdout
    ttl = code / "provenance.ttl"
    ttl.write_text(ttl.read_text() + f'\n<{DATA_ENT}> <https://w3id.org/aiprov/ns#filePath> "restricted/x.yaml" .\n')
    r = run(B_CODE, ["validate"], code)
    assert r.returncode != 0 and "carry a file path or a label: 1" in r.stdout
