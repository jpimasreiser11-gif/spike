"""Glossaries: terms and the wording the user wants, global and per project, applied as rules in the prompt when a
term appears in the conversation, with the API and CSV in and out."""

import pytest
from fastapi.testclient import TestClient

from spike.core.context import estimate_tokens
from spike.memory.glossary import Glossary, GlossaryError, fold, glossary_lines
from spike.memory.service import Recall, memory_prompt
from spike.memory.store import GLOBAL, MemoryStore
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text
from tests.test_memory import events_of, no_embedder


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    yield s
    s.close()


@pytest.fixture
def glossary(store):
    return Glossary(store)


def test_a_term_has_one_entry_per_language_and_scope(glossary):
    glossary.add("invoice", "factura", "es")
    glossary.add("invoice", "fatura", "pt")  # another language: another entry
    glossary.add("invoice", "factura de proyecto", "es", scope="project:p1")  # another scope
    with pytest.raises(GlossaryError, match="already"):
        glossary.add("Invoice", "otra", "es")  # case and accents do not make a new term
    with pytest.raises(GlossaryError):
        glossary.add("", "x")
    with pytest.raises(GlossaryError):
        glossary.add("x", "y", lang="not a language code!")
    with pytest.raises(GlossaryError, match="too long"):
        glossary.add("x" * 201, "y")
    assert [e.lang for e in glossary.list(scope=GLOBAL)] == ["es", "pt"]
    entry = glossary.list(scope=GLOBAL)[0]
    assert glossary.update(entry.id, translation="la factura").translation == "la factura"
    with pytest.raises(GlossaryError):
        glossary.update(entry.id, lang="pt")  # would collide with the Portuguese entry
    assert glossary.update("nope", term="x") is None
    assert glossary.delete(entry.id) and not glossary.delete(entry.id)
    assert [e.translation for e in glossary.list(q="FACT")] == ["factura de proyecto"]  # by wording, ignoring case


def test_terms_are_found_as_whole_words_ignoring_case_and_accents(glossary):
    glossary.add("invoice", "factura", "es")
    glossary.add("ARA-II", "antagonista del receptor de la angiotensina II")
    glossary.add("Año fiscal", "fiscal year", "en")
    glossary.add("C++", "C plus plus", "en")
    scopes = [GLOBAL]
    assert [e.term for e in glossary.match("Please send the INVOICE today", scopes)] == ["invoice"]
    assert glossary.match("the invoices are late", scopes) == []  # not inside another word
    assert glossary.match("preinvoice", scopes) == []
    assert [e.term for e in glossary.match("¿Cuándo empieza el ano fiscal?", scopes)] == ["Año fiscal"]
    assert [e.term for e in glossary.match("tratamiento con ARA-II, según la guía", scopes)] == ["ARA-II"]
    assert [e.term for e in glossary.match("I code in c++ and Rust", scopes)] == ["C++"]
    assert glossary.match("", scopes) == [] and glossary.match("nothing relevant", scopes) == []


def test_a_projects_entry_beats_the_global_one_and_other_projects_are_invisible(glossary):
    glossary.add("invoice", "factura", "es")
    glossary.add("invoice", "factura fiscal", "es", scope="project:p1")
    glossary.add("invoice", "nota de cobro", "es", scope="project:p2")
    glossary.add("budget", "presupuesto", "es", scope="project:p2")
    found = glossary.match("invoice and budget", ["project:p1", GLOBAL])
    assert [(e.term, e.translation) for e in found] == [("invoice", "factura fiscal")]
    assert [e.translation for e in glossary.match("invoice", [GLOBAL])] == ["factura"]
    assert sorted(e.term for e in glossary.match("invoice and budget", ["project:p2", GLOBAL])) == ["budget", "invoice"]


def test_the_prompt_lists_matching_terms_as_rules_within_a_quarter_of_the_budget(glossary):
    glossary.add("invoice", "factura", "es", note="siempre en femenino")
    glossary.add("ARA-II", "antagonista del receptor de la angiotensina II")
    found = glossary.match("invoice ARA-II", [GLOBAL])
    assert glossary_lines(found) == ["- ARA-II: antagonista del receptor de la angiotensina II",
                                     "- invoice → factura (es) [siempre en femenino]"]
    prompt = memory_prompt(Recall(glossary=found), 1000)
    assert prompt.startswith("# Glossary") and "use exactly these terms" in prompt and "invoice → factura (es)" in prompt
    assert Recall(glossary=found).event()["glossary"] == ["ARA-II", "invoice"]  # shown on the answer
    assert Recall().event() is None and memory_prompt(Recall(), 1000) == ""
    for i in range(80):
        glossary.add(f"término{i}", "traducción larga " * 6, "es")
    many = glossary.match(" ".join(f"término{i}" for i in range(80)), [GLOBAL])
    assert len(many) == 80
    for budget in (200, 800):
        block = memory_prompt(Recall(glossary=many), budget)
        assert 0 < estimate_tokens(block) <= budget // 4 + 10, budget


def test_csv_round_trip_keeps_text_and_does_not_start_a_formula(glossary, tmp_path):
    glossary.add("invoice", "factura", "es", "dos, tres")
    glossary.add("=SUM(A1)", "+suma", "es", "-nota")
    glossary.add("Línea\ncorta", "dice \"hola\"", "")
    csv_text = glossary.export_csv(GLOBAL)
    lines = csv_text.splitlines()
    assert lines[0] == "term,translation,lang,note"
    assert "'=SUM(A1)" in csv_text and "'+suma" in csv_text and "'-nota" in csv_text  # text, not a formula
    other = Glossary(MemoryStore(tmp_path / "other.db"))
    result = other.import_csv(csv_text, GLOBAL)
    assert result == {"added": 3, "updated": 0, "errors": [], "skipped": 0}
    assert {(e.term, e.translation, e.lang, e.note) for e in other.list()} == {
        (e.term, e.translation, e.lang, e.note) for e in glossary.list()}
    assert other.import_csv(csv_text, GLOBAL)["updated"] == 3  # the same file again changes nothing but the stamps
    other.store.close()


def test_import_accepts_semicolons_other_headers_a_bom_and_reports_bad_rows(glossary):
    glossary.add("invoice", "factura vieja", "es")
    data = ("﻿Término;Traducción;Idioma;Nota\n"
            "invoice;factura;es;ya existía\n"        # updates the entry above
            "budget;presupuesto;es;\n"
            ";sin término;es;\n"                      # no term
            "mal;código;español neto!;\n"              # bad language
            "\n"
            "refund;reembolso;es;\n").encode()
    result = glossary.import_csv(data, GLOBAL)
    assert (result["added"], result["updated"], result["skipped"]) == (2, 1, 2)
    assert [e["line"] for e in result["errors"]] == [4, 5]
    assert {e.term: e.translation for e in glossary.list()} == {
        "invoice": "factura", "budget": "presupuesto", "refund": "reembolso"}
    # no header: columns by position
    assert glossary.import_csv("tax,impuesto,es\n", GLOBAL)["added"] == 1
    with pytest.raises(GlossaryError, match="no rows"):
        glossary.import_csv("\n\n", GLOBAL)


# ------------------------------------------------------------------------------------------- API and chats
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


def system_of(local):
    return local.requests[-1].messages[0].content


def test_glossary_api_crud_and_csv(api):
    client, state, _ = api
    pid = client.post("/api/projects", json={"name": "Contrato"}).json()["id"]
    made = client.post("/api/glossary", json={"term": "invoice", "translation": "factura", "lang": "es"}).json()
    assert made["scope"] == "global" and made["lang"] == "es"
    assert client.post("/api/glossary", json={"term": "invoice", "translation": "x", "lang": "es"}).status_code == 400
    assert client.post("/api/glossary", json={"term": "a", "translation": "b", "scope": "project:nope"}).status_code == 400
    client.post("/api/glossary", json={"term": "budget", "translation": "presupuesto", "lang": "es",
                                       "scope": f"project:{pid}"})
    assert [e["term"] for e in client.get("/api/glossary").json()] == ["budget", "invoice"]
    assert [e["term"] for e in client.get(f"/api/glossary?scope=project:{pid}").json()] == ["budget"]
    assert client.get("/api/glossary?q=factura").json()[0]["id"] == made["id"]
    assert client.put(f"/api/glossary/{made['id']}", json={"translation": "la factura"}).json()["translation"] == "la factura"
    assert client.put("/api/glossary/nope", json={"term": "x"}).status_code == 404
    exported = client.get("/api/glossary-export")
    assert exported.headers["content-disposition"].startswith("attachment") and exported.headers["content-type"].startswith("text/csv")
    assert exported.content.startswith(b"\xef\xbb\xbfterm,translation,lang,note")
    assert client.delete(f"/api/glossary/{made['id']}").json() == {"ok": True}
    assert client.delete(f"/api/glossary/{made['id']}").status_code == 404
    imported = client.post(f"/api/glossary-import?scope=project:{pid}", content=exported.content)
    assert imported.json()["added"] == 1 and client.get(f"/api/glossary?scope=project:{pid}").json()[1]["term"] == "invoice"
    assert client.post("/api/glossary-import", content=b"").status_code == 400
    assert client.post("/api/glossary-import?scope=project:nope", content=b"a,b\n").status_code == 400
    big = client.post("/api/glossary-import", content=b"x" * (5 * 1024**2 + 1))
    assert big.status_code == 413


def test_a_chat_gets_the_terms_that_appear_in_it_or_in_the_last_turns(api):
    client, state, local = api
    client.post("/api/glossary", json={"term": "invoice", "translation": "factura", "lang": "es"})
    client.post("/api/glossary", json={"term": "warranty", "translation": "garantía", "lang": "es"})
    local._script = [text("ok")]
    events = client.post("/api/chat", json={"message": "Translate: please pay the invoice"})
    system = system_of(local)
    assert "# Glossary" in system and "- invoice → factura (es)" in system and "warranty" not in system
    chip = next(e for e in events_of(events) if e["type"] == "memory")
    assert chip["glossary"] == ["invoice"] and chip["rules"] == 0 and chip["notes"] == []
    cid = client.get("/api/conversations").json()[0]["id"]
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "And in the next sentence?", "conversation_id": cid})
    assert "- invoice → factura (es)" in system_of(local)  # the term was in an earlier turn of this chat
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "Hello there"})
    assert "# Glossary" not in system_of(local)


def test_project_glossaries_apply_in_that_project_only(api):
    client, state, local = api
    pid = client.post("/api/projects", json={"name": "Cliente"}).json()["id"]
    client.post("/api/glossary", json={"term": "deliverable", "translation": "entregable", "lang": "es"})
    client.post("/api/glossary", json={"term": "deliverable", "translation": "producto entregable", "lang": "es",
                                       "scope": f"project:{pid}"})
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "Review the deliverable", "project_id": pid})
    assert "deliverable → producto entregable (es)" in system_of(local) and "→ entregable" not in system_of(local)
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "Review the deliverable"})
    assert "deliverable → entregable (es)" in system_of(local)
    client.delete(f"/api/projects/{pid}")
    assert client.get("/api/glossary").json() != [] and state.memory.glossary.list(scope=f"project:{pid}") == []


def test_no_glossary_in_temporary_chats_or_with_memory_off(api):
    client, state, local = api
    client.post("/api/glossary", json={"term": "invoice", "translation": "factura", "lang": "es"})
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "the invoice", "temporary": True})
    assert "# Glossary" not in system_of(local)
    state.update_settings({"memory": {"enabled": False, "embeddings": "auto", "auto_summary": True}})
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "the invoice"})
    assert "# Glossary" not in system_of(local)
    assert fold("  Ámbito   Fiscal ") == "ambito fiscal"
