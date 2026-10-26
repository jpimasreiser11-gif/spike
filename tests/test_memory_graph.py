"""Knowledge graph over Neural Memory: deterministic entity extraction, notes linked by shared entities, relations a
model proposes and the user confirms, neighbours through the API, the SVG for the artifacts panel, and nothing left
in the database file after a note is deleted."""

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from spike.memory.extract_entities import extract
from spike.memory.graph import Graph, GraphError
from spike.memory.graph_svg import layout, render_svg
from spike.memory.store import GLOBAL, MemoryStore
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text
from tests.test_memory import no_embedder


def found(sample: str) -> set[tuple[str, str]]:
    return {(e.kind, e.name) for e, _ in extract(sample)}


# ------------------------------------------------------------------------------------------- extraction
def test_names_emails_dates_quantities_and_links_are_found_by_patterns():
    sample = ("Reunión con María García de Acme Corp el 3 de noviembre de 2026. Escribir a Maria@Acme.com. El contrato "
              "vale 12.500 € y vence en 30 días. Más info: https://acme.example/contrato. Usamos PostgreSQL y la guía ESC.")
    assert found(sample) == {
        ("name", "María García"), ("name", "Acme Corp"), ("date", "2026-11-03"), ("email", "maria@acme.com"),
        ("quantity", "12.500 €"), ("quantity", "30 días"), ("link", "https://acme.example/contrato"),
        ("name", "PostgreSQL"), ("name", "ESC")}
    english = ("Meeting on November 3, 2026 with Banco de España; budget $40 and 5 GB; call 03/11/2026 or 2026-11-04. "
               "Universidad de Salamanca, Plan Atlas.")
    assert found(english) == {("date", "2026-11-03"), ("name", "Banco de España"), ("quantity", "$40"),
                              ("quantity", "5 GB"), ("date", "2026-11-04"), ("name", "Universidad de Salamanca"),
                              ("name", "Plan Atlas")}
    counted = {e.key: n for e, n in extract(english)}
    assert counted["2026-11-03"] == 2  # written two ways, one date


def test_a_word_that_only_starts_a_sentence_is_not_a_name():
    assert found("Decidimos usar el motor. Mañana revisamos todo. Hoy hablé con Marta.") == {("name", "Marta")}
    assert found("Toby es un perro. El perro se llama Toby.") == {("name", "Toby")}  # it also shows up mid-sentence
    assert found("Ayer Pedro llamó. El Cliente Norte paga.") == {("name", "Pedro"), ("name", "Cliente Norte")}
    assert found("Visité La Habana el Lunes con Juan de la Cruz.") == {("name", "Habana"), ("name", "Juan de la Cruz")}
    assert found("el lunes y el 5 de mayo, sin nombres, 12 gatos") == {("date", "5 de mayo")}
    assert [e.key for e, _ in extract("el 5 de mayo")] == ["--05-05"]  # no year: the day of every year
    assert found("") == set()


def test_a_lone_word_that_opens_a_sentence_is_a_name_unless_it_looks_like_an_ordinary_word():
    assert found("Lucía vive en Lyon. Toby es su perro.") == {("name", "Lucía"), ("name", "Lyon"), ("name", "Toby")}
    assert found("Acme usa SQLite y PostgreSQL.") == {("name", "Acme"), ("name", "SQLite"), ("name", "PostgreSQL")}
    # verbs, adverbs, abstract nouns, headings and function words are not entities
    assert found("Revisamos todo. Pidió ayuda. Hablé con ella. Planning aparte. Resultados buenos. Realmente bien.") == set()
    assert found("Resumen\n## Tareas\n**Ideas**:\nMarta llamó.") == {("name", "Marta")}
    assert found("Hay un plan. Pero Lucía no vino. We met Sam. Here it is.") == {("name", "Lucía"), ("name", "Sam")}


def test_numbers_need_a_unit_and_impossible_dates_are_not_dates():
    assert found("Hay 12 gatos y 3 perros. Es el 31/02/2026 o el 45/13/2026, y pesa 1,5 kg, o 2 000 mg y 40%.") == {
        ("quantity", "1,5 kg"), ("quantity", "2 000 mg"), ("quantity", "40%")}
    assert found("a 10m del pozo, 8h de trabajo y 7 s de espera") == {("quantity", "10m"), ("quantity", "8h")}
    keys = {e.key for e, _ in extract("Costó 12.500,50 € o 12,500.5 euros, o $1,500 y 1,5 kg y 3.000 mg")}
    assert keys == {"12500.50 €", "12500.5 euros", "1500 $", "1.5 kg", "3000 mg"}


def test_a_huge_text_is_cut_and_the_most_frequent_entities_win():
    many = " ".join(f"visita a Ciudad{chr(65 + i % 26)}{chr(97 + i // 26 % 26)}ejo" for i in range(300))
    assert len(extract("Lyon, Lyon, Lyon. " + many)) <= 120
    assert extract("a ' Lyon, Lyon, Lyon" + " x" * 10)[0][0].name == "Lyon"
    assert extract("A" * 500_000) == []


# ------------------------------------------------------------------------------------------- the graph
@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    yield s
    s.close()


@pytest.fixture
def graph(store):
    return Graph(store)


def fill(store):
    a = store.add("Reunión con María García de Acme Corp el 3 de noviembre de 2026.", "fact")
    b = store.add("María García prefiere que le escriban a maria@acme.com. El contrato de Acme Corp vale 12.500 €.", "fact")
    c = store.add("Acme Corp usa PostgreSQL. El plazo es de 30 días.", "decision")
    d = store.add("Toby es el perro de Lucía. Lucía vive en Lyon.", "fact", scope="project:p1")
    return a, b, c, d


def ids(data):
    return {n["label"]: n["id"] for n in data["nodes"]}


def test_sync_reads_only_new_and_changed_notes(store, graph):
    a, b, c, d = fill(store)
    assert graph.sync() == 4 and graph.sync() == 0
    by_name = {e["label"]: e for e in graph.entities([GLOBAL, "project:p1"])}
    assert by_name["Acme Corp"]["weight"] == 3 and by_name["María García"]["weight"] == 2
    assert {e["label"] for e in graph.entities([GLOBAL], kind="email")} == {"maria@acme.com"}
    assert [e["label"] for e in graph.entities([GLOBAL], q="gar")] == ["María García"]  # ignoring accents and case
    assert "Lucía" not in {e["label"] for e in graph.entities([GLOBAL])}  # another scope's entities stay out
    store.update(c.id, "Acme Corp cambió a SQLite.")
    assert graph.sync() == 1
    names = {e["label"] for e in graph.entities([GLOBAL])}
    assert "SQLite" in names and "PostgreSQL" not in names and "30 días" not in names


def test_deleting_a_note_removes_its_entities_and_leaves_nothing_in_the_file(store, graph, tmp_path):
    keep = store.add("Reunión con Zacarías Quintanilla de Acme Corp", "fact")
    secret = store.add("La clave de Fernanda Zumbadora es zanahoriasecreta42, escribir a fernanda@zumbadora.example", "fact")
    graph.sync()
    assert {e["label"] for e in graph.entities([GLOBAL])} >= {"Fernanda Zumbadora", "fernanda@zumbadora.example"}
    assert store.delete(secret.id)
    assert {e["label"] for e in graph.entities([GLOBAL])} == {"Zacarías Quintanilla", "Acme Corp"}
    db = store._db
    assert db.execute("SELECT COUNT(*) FROM entities WHERE name LIKE '%Zumbadora%'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM mentions WHERE memory_id = ?", (secret.id,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM graph_seen WHERE memory_id = ?", (secret.id,)).fetchone()[0] == 0
    raw = (tmp_path / "memory.db").read_bytes()
    assert b"Zumbadora" not in raw and b"zumbadora" not in raw and b"zanahoriasecreta42" not in raw
    assert store.get(keep.id) is not None and store.delete_scope("global")
    assert db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0 and b"Quintanilla" not in (
        tmp_path / "memory.db").read_bytes()


def test_neighbours_of_an_entity_are_its_notes_and_the_entities_that_share_them(store, graph):
    a, b, c, d = fill(store)
    graph.sync()
    scopes = [GLOBAL]
    overview = graph.graph(scopes, limit=20)
    acme = ids(overview)["Acme Corp"]
    assert overview["focus"] is None and all(n["type"] == "entity" or n["id"].startswith("m:") for n in overview["nodes"])
    around = graph.graph(scopes, node=acme, depth=1)
    labels = ids(around)
    assert {"María García", "PostgreSQL", "maria@acme.com", "12.500 €", "2026-11-03"} <= set(labels)
    assert {f"m:{a.id}", f"m:{b.id}", f"m:{c.id}"} <= set(labels.values())  # the three notes that mention it
    assert f"m:{d.id}" not in labels.values() and "Lucía" not in labels  # a project's notes stay in the project
    mentions = [e for e in around["edges"] if e["type"] == "mentions"]
    assert {e["source"] for e in mentions} == {f"m:{a.id}", f"m:{b.id}", f"m:{c.id}"} and all(e["target"] == acme for e in mentions)
    co = {(e["source"], e["target"]): e["weight"] for e in around["edges"] if e["type"] == "cooccur"}
    assert co[(acme, labels["María García"])] == 2  # together in two notes
    # without notes only entities remain; a smaller limit caps the picture
    assert all(n["type"] == "entity" for n in graph.graph(scopes, node=acme, notes=False)["nodes"])
    assert len(graph.graph(scopes, node=acme, limit=4)["nodes"]) <= 4


def test_neighbours_of_a_note_are_its_entities_and_the_notes_that_share_them(store, graph):
    a, b, c, d = fill(store)
    graph.sync()
    around = graph.graph([GLOBAL], node=f"m:{a.id}")
    labels = ids(around)
    assert {"María García", "Acme Corp", "2026-11-03"} <= set(labels) and f"m:{b.id}" in labels.values()
    shared = next(e for e in around["edges"] if e["type"] == "shared" and f"m:{b.id}" in (e["source"], e["target"]))
    assert shared["weight"] == 2 and "Acme Corp" in shared["label"] and "María García" in shared["label"]
    assert f"m:{c.id}" in labels.values()  # shares Acme Corp with the first note
    assert f"m:{d.id}" not in labels.values()
    deeper = graph.graph([GLOBAL], node=f"m:{a.id}", depth=2, limit=40)
    assert {"PostgreSQL", "maria@acme.com"} <= {n["label"] for n in deeper["nodes"]}
    with pytest.raises(GraphError, match="not in the graph"):
        graph.graph([GLOBAL], node="m:nope")
    with pytest.raises(GraphError, match="not in the graph"):
        graph.graph([GLOBAL], node=f"m:{d.id}")  # exists, but not in these scopes
    with pytest.raises(GraphError):
        graph.graph([GLOBAL], node="e:999999")
    with pytest.raises(GraphError, match="depth"):
        graph.graph([GLOBAL], depth=9)


def test_an_entity_in_too_many_notes_does_not_link_them_all(store, graph, monkeypatch):
    import spike.memory.graph as graph_module

    monkeypatch.setattr(graph_module, "HUB_NOTES", 3)
    notes = [store.add(f"Informe número {i} de Acme Corp sobre Tema{'ABCDEFGH'[i]}ejo", "fact") for i in range(5)]
    first = store.add("Nota con Quimera Rara", "fact")
    second = store.add("Otra nota con Quimera Rara", "fact")
    graph.sync()
    linked = {n["id"] for n in graph.graph([GLOBAL], node=f"m:{notes[0].id}")["nodes"] if n["type"] == "note"}
    assert linked == {f"m:{notes[0].id}"}  # Acme Corp is in 5 notes: a hub
    twin = graph.graph([GLOBAL], node=f"m:{first.id}")
    assert f"m:{second.id}" in {n["id"] for n in twin["nodes"]}


# ------------------------------------------------------------------------------------------- relations
def test_proposed_relations_wait_for_the_user_and_rejected_ones_stay_rejected(store, graph):
    a, b, c, d = fill(store)
    graph.sync()
    saved = graph.propose(a.id, [("María García", "trabaja en", "Acme Corp"), ("Acme Corp", "usa", "Inventada SL"),
                                 ("María García", "es", "María García"), ("María García", "trabaja en", "Acme Corp"),
                                 ("María García", " ", "Acme Corp"), ("2026-11-03", "fecha de", "Acme Corp")])
    assert [(r["from"], r["label"], r["to"], r["status"]) for r in saved] == [
        ("María García", "trabaja en", "Acme Corp", "proposed"), ("2026-11-03", "fecha de", "Acme Corp", "proposed")]
    scopes = [GLOBAL]
    plain = graph.graph(scopes, node=ids(graph.graph(scopes))["Acme Corp"])
    assert not [e for e in plain["edges"] if e["type"] == "relation"]  # nothing unconfirmed is in the picture
    with_proposals = graph.graph(scopes, node=ids(graph.graph(scopes))["Acme Corp"], proposed=True)
    assert {e["label"] for e in with_proposals["edges"] if e["type"] == "relation"} == {"trabaja en", "fecha de"}
    first = saved[0]["id"]
    assert graph.set_status(first, "confirmed")["status"] == "confirmed"
    assert {e["label"] for e in graph.graph(scopes, node=ids(graph.graph(scopes))["Acme Corp"])["edges"]
            if e["type"] == "relation"} == {"trabaja en"}
    assert graph.set_status(saved[1]["id"], "rejected")["status"] == "rejected"
    assert graph.propose(a.id, [("2026-11-03", "fecha de", "Acme Corp")]) == []  # a rejected one is not proposed again
    assert [r["label"] for r in graph.relations(scopes, "rejected")] == ["fecha de"]
    assert graph.stats(scopes)["relations"] == 1 and graph.stats(scopes)["proposed"] == 0
    with pytest.raises(GraphError):
        graph.set_status(first, "maybe")
    assert graph.set_status("nope", "confirmed") is None
    with pytest.raises(GraphError, match="not found"):
        graph.propose("nope", [])


def test_a_proposal_goes_when_its_note_goes_and_a_hand_made_relation_stays_until_deleted(store, graph, tmp_path):
    a, b, c, d = fill(store)
    graph.sync()
    proposal = graph.propose(a.id, [("María García", "trabaja en", "Acme Corp")])[0]
    graph.set_status(proposal["id"], "confirmed")
    mine = graph.add_relation(GLOBAL, "PostgreSQL", "es una base de datos de", "Acme Corp")
    assert mine["status"] == "confirmed" and mine["origin"] == "user"
    assert graph.add_relation(GLOBAL, "PostgreSQL", "es una base de datos de", "Acme Corp")["id"] == mine["id"]
    for bad in (("PostgreSQL", "x", "PostgreSQL"), ("PostgreSQL", "x", "Inventada"), ("PostgreSQL", " ", "Acme Corp")):
        with pytest.raises(GraphError):
            graph.add_relation(GLOBAL, *bad[:1], bad[1], bad[2])
    store.delete(a.id)
    assert [r["label"] for r in graph.relations([GLOBAL])] == ["es una base de datos de"]
    assert graph.delete_relation(mine["id"]) and not graph.delete_relation(mine["id"])
    for note in (b, c, d):
        store.delete(note.id)
    db = store._db
    assert db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0 and db.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
    assert b"PostgreSQL" not in (tmp_path / "memory.db").read_bytes()


def test_clearing_a_scope_drops_its_hand_made_relations(store, graph):
    store.add("Lucía vive en Lyon con Toby", "fact", scope="project:p1")
    graph.sync()
    graph.add_relation("project:p1", "Lucía", "vive en", "Lyon")
    assert graph.delete_scope("project:p1") == 1 and graph.relations(["project:p1"]) == []
    assert graph.delete_scope(None) == 0


# ------------------------------------------------------------------------------------------- the picture
def svg_of(graph, scopes, **kw):
    return render_svg(graph.graph(scopes, **kw), kw.pop("lang", "en"))


def test_the_svg_is_well_formed_script_free_and_the_same_every_time(store, graph):
    fill(store)
    graph.sync()
    data = graph.graph([GLOBAL], node=ids(graph.graph([GLOBAL]))["Acme Corp"], proposed=True)
    first, again = render_svg(data, "en"), render_svg(data, "en")
    assert first == again  # fixed starting points and steps: the same graph draws the same
    root = ET.fromstring(first)  # well-formed XML
    assert root.tag == "{http://www.w3.org/2000/svg}svg" and root.get("role") == "img"
    assert "<script" not in first and "javascript:" not in first and "href=" not in first and "http://" not in first.replace(
        "http://www.w3.org/2000/svg", "")
    namespace = {"s": "http://www.w3.org/2000/svg"}
    labels = [t.text for t in root.iterfind(".//s:text", namespace)]
    assert "Acme Corp" in labels and "María García" in labels and any("Memory graph" in (t or "") for t in labels)
    assert root.find(".//s:circle", namespace) is not None and root.find(".//s:rect[@class='note ']", namespace) is not None
    assert render_svg(data, "es").count("Grafo de la memoria") >= 2 and "Nombre" in render_svg(data, "es")
    for x, y in layout(data["nodes"], data["edges"], data["focus"]).values():
        assert 0 <= x <= 960 and 0 <= y <= 640


def test_the_svg_marks_proposed_relations_and_escapes_what_the_notes_say(store, graph):
    note = store.add("Mira <script>alert(1)</script> en Zorro&Co con Lucía Fernández y \x07 campana", "fact")
    store.add("Lucía Fernández vive en Lyon", "fact")
    graph.sync()
    graph.propose(note.id, [("Lucía Fernández", "conoce a", "Zorro")])
    data = graph.graph([GLOBAL], node=ids(graph.graph([GLOBAL]))["Lucía Fernández"], proposed=True)
    svg = render_svg(data, "en", title="Lucía <b>")
    ET.fromstring(svg)  # still well-formed with markup characters and a control character in the notes
    assert "<script" not in svg and "&lt;b&gt;" in svg and "\x07" not in svg
    assert 'class="e e-proposed"' in svg and "proposed relation, not confirmed" in svg
    assert "conoce a" in svg and "dasharray" in svg
    empty = render_svg({"nodes": [], "edges": [], "focus": None}, "es")
    ET.fromstring(empty)
    assert "Todavía no hay entidades" in empty


# ------------------------------------------------------------------------------------------- API
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    state.memory.get_embedder = no_embedder
    with TestClient(create_app(state)) as client:
        yield client, state, local


def test_graph_api_serves_the_overview_neighbours_entities_and_the_svg(api):
    client, state, _ = api
    pid = client.post("/api/projects", json={"name": "Proyecto"}).json()["id"]
    fill(state.memory.store)
    state.memory.store.add("Lucía vive en Lyon con Toby", "fact", scope=f"project:{pid}")
    overview = client.get("/api/memory-graph").json()
    assert overview["stats"]["entities"] >= 8 and {"Acme Corp", "Lucía", "Lyon"} <= {n["label"] for n in overview["nodes"]}
    only_global = client.get("/api/memory-graph?scope=global").json()
    assert "Lucía" not in {n["label"] for n in only_global["nodes"]}
    acme = ids(only_global)["Acme Corp"]
    near = client.get(f"/api/memory-graph?scope=global&node={acme}&depth=1&limit=12").json()
    assert near["focus"] == acme and len(near["nodes"]) <= 12 and near["edges"]
    assert client.get("/api/memory-graph?node=e:99999").status_code == 400
    assert client.get("/api/memory-graph?depth=7").status_code == 400
    assert client.get("/api/memory-graph?scope=project:nope").status_code == 400
    ents = client.get("/api/memory-graph/entities?scope=global&q=acme").json()
    assert {e["label"]: e["weight"] for e in ents} == {"Acme Corp": 3, "maria@acme.com": 1}  # by name or e-mail
    svg = client.get(f"/api/memory-graph/svg?scope=global&node={acme}&lang=es")
    assert svg.headers["content-type"].startswith("image/svg+xml") and "default-src 'none'" in svg.headers["content-security-policy"]
    ET.fromstring(svg.text)
    assert "Grafo de la memoria" not in svg.text and "Acme Corp" in svg.text  # the focus names the picture
    assert "Nombre" in svg.text
    assert client.get("/api/memory-graph/svg?scope=global").text.count("Memory graph") >= 1


def test_relations_api_proposes_with_a_local_model_and_the_user_decides(api):
    client, state, local = api
    note = state.memory.store.add("María García trabaja en Acme Corp desde 2020. Escribe a maria@acme.com.", "fact")
    local._script = [text('Claro:\n{"relations": [{"from": "María García", "label": "trabaja en", "to": "Acme Corp"}, '
                          '{"from": "Fantasma", "label": "x", "to": "Acme Corp"}, "basura"]}')]
    proposed = client.post("/api/memory-graph/propose", json={"memory_id": note.id}).json()["proposed"]
    assert [(r["from"], r["label"], r["to"], r["status"]) for r in proposed] == [
        ("María García", "trabaja en", "Acme Corp", "proposed")]
    request = local.requests[-1]
    assert "María García" in request.messages[1].content and "NOTE:" in request.messages[1].content
    assert request.json_schema is None or "relations" in request.json_schema["properties"]
    assert client.get("/api/memory-graph/relations?status=proposed").json()[0]["id"] == proposed[0]["id"]
    rid = proposed[0]["id"]
    assert client.patch(f"/api/memory-graph/relations/{rid}", json={"status": "confirmed"}).json()["status"] == "confirmed"
    assert client.patch(f"/api/memory-graph/relations/{rid}", json={"status": "maybe"}).status_code == 422
    assert client.patch("/api/memory-graph/relations/nope", json={"status": "confirmed"}).status_code == 404
    acme = next(e["id"] for e in client.get("/api/memory-graph/entities?q=acme").json())
    edges = client.get(f"/api/memory-graph?node={acme}").json()["edges"]
    assert [e["label"] for e in edges if e["type"] == "relation"] == ["trabaja en"]
    mine = client.post("/api/memory-graph/relations", json={"source": "maria@acme.com", "label": "contacto de",
                                                           "target": "María García"})
    assert mine.status_code == 200 and mine.json()["origin"] == "user"
    assert client.post("/api/memory-graph/relations", json={"source": "x", "label": "y", "target": "z"}).status_code == 400
    assert client.delete(f"/api/memory-graph/relations/{rid}").json() == {"ok": True}
    assert client.delete(f"/api/memory-graph/relations/{rid}").status_code == 404
    # garbage from the model proposes nothing; unknown notes and notes with one entity are handled
    local._script = [text("no sé")]
    assert client.post("/api/memory-graph/propose", json={"memory_id": note.id}).json() == {"proposed": []}
    assert client.post("/api/memory-graph/propose", json={"memory_id": "nope"}).status_code == 404
    lonely = state.memory.store.add("Solo habla de Marte", "fact")
    assert client.post("/api/memory-graph/propose", json={"memory_id": lonely.id}).json() == {"proposed": []}


def test_a_model_that_is_not_local_is_never_asked_about_a_note(api):
    client, state, local = api
    note = state.memory.store.add("María García trabaja en Acme Corp", "fact")
    state.provider("spike-local")  # created now, so the flag set below is not reset by the factory
    local.config.local = False
    calls = len(local.requests)
    r = client.post("/api/memory-graph/propose", json={"memory_id": note.id})
    assert r.status_code == 409 and "local model" in r.json()["detail"] and len(local.requests) == calls


def test_a_failing_model_is_reported_not_raised(api):
    client, state, local = api
    note = state.memory.store.add("María García trabaja en Acme Corp", "fact")
    from spike.core.types import StreamEvent
    local._script = [[StreamEvent(kind="error", text="boom")]]
    assert client.post("/api/memory-graph/propose", json={"memory_id": note.id}).status_code == 503


def test_clearing_memory_clears_the_graph_with_it(api):
    client, state, _ = api
    note = state.memory.store.add("María García trabaja en Acme Corp", "fact")
    state.memory.graph.sync()
    state.memory.graph.add_relation(GLOBAL, "María García", "trabaja en", "Acme Corp")
    assert client.delete("/api/memory?scope=all").json()["deleted"] == 1
    assert client.get("/api/memory-graph").json()["nodes"] == [] and state.memory.store.get(note.id) is None
    assert state.memory.store._db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
