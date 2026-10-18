"""Neural Memory: storage, hybrid search (words + meaning), token budget, deletion that leaves nothing behind,
the API, project files, and recall and summaries in chats."""

import json

import pytest
from fastapi.testclient import TestClient

from spike.core.context import estimate_tokens
from spike.memory.service import Embedder, MemoryService, Recall, memory_prompt
from spike.memory.store import CHUNK_CHARS, GLOBAL, MemoryStore, chunk_text
from spike.runtime.llamacpp_server import LlamaServer, ServerConfig, find_binary
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text

# A stand-in for an embedding model: words that mean the same thing share a dimension, so search by meaning
# can be tested without weights.
CONCEPTS = {"coche": 0, "automovil": 0, "vehiculo": 0, "car": 0, "perro": 1, "mascota": 1, "dog": 1,
            "factura": 2, "facturacion": 2, "invoice": 2, "billing": 2, "postgres": 3, "postgresql": 3, "base": 3}


class ConceptEmbedder(Embedder):
    def __init__(self):
        super().__init__("http://unused", model="concepts-v1")
        self.calls = 0

    async def embed(self, texts, query=False):
        import re
        import unicodedata

        self.calls += 1
        out = []
        for t in texts:
            norm = "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))
            v = [0.0] * 8
            for w in re.findall(r"[a-z]+", norm):
                if w in CONCEPTS:
                    v[CONCEPTS[w]] += 1.0
            v[7] = 0.05  # every text points a little the same way, like real embeddings
            out.append(v)
        return out


async def no_embedder():
    return None


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    yield s
    s.close()


def test_chunks_keep_paragraphs_and_stay_under_the_size():
    text = "\n\n".join(f"Párrafo {i}. " + "palabra " * 60 for i in range(12)) + "\n\n" + "x" * 3000
    chunks = chunk_text(text)
    assert all(len(c) <= CHUNK_CHARS for c in chunks)
    assert chunks[0].startswith("Párrafo 0.") and "".join(chunks).replace("\n", "").count("x") == 3000
    assert chunk_text("corto") == ["corto"] and chunk_text("  ") == []


def test_word_search_ignores_accents_and_respects_scopes(store):
    store.add("Decidimos usar PostgreSQL para la facturación del cliente Norte", "decision")
    store.add("La tesis cita a Pérez (2021) sobre hipertensión", "fact", scope="project:p1")
    store.add("Nota privada de otro proyecto sobre facturacion", "fact", scope="project:p2")
    hits = store.search("¿qué base usamos para la facturacion?", [GLOBAL])
    assert [h.memory.kind for h in hits] == ["decision"] and hits[0].by == ["words"]
    in_p1 = store.search("facturación hipertensión", ["project:p1", GLOBAL])
    assert {h.memory.scope for h in in_p1} == {"project:p1", GLOBAL}  # global is visible inside a project
    assert not any(h.memory.scope == "project:p2" for h in in_p1)


async def test_hybrid_search_finds_by_meaning_and_ranks_double_matches_first(store):
    service = MemoryService(store, lambda: _ret(ConceptEmbedder()))
    store.add("Mi coche es un Seat Ibiza rojo de 2019", "fact")
    store.add("El perro se llama Toby", "fact")
    store.add("Las facturas se emiten el día 5", "fact")
    assert await service.index() == 3
    found = await service.recall("¿Qué automóvil tengo?", None)
    assert found.semantic and [h.memory.text for h in found.hits] == ["Mi coche es un Seat Ibiza rojo de 2019"]
    assert found.hits[0].by == ["meaning"]  # no shared word: found by meaning alone
    store.add("Facturación: el coche de empresa se factura aparte", "fact")
    await service.index()
    both = await service.recall("factura del vehículo", None)
    assert both.hits[0].memory.text.startswith("Facturación") and both.hits[0].by == ["meaning", "words"]


async def _ret(value):
    return value


async def test_semantic_search_failure_falls_back_to_words(store):
    class Broken(ConceptEmbedder):
        async def embed(self, texts, query=False):
            raise OSError("embedding server is down")

    store.add("Prefiere respuestas en tablas", "preference")
    found = await MemoryService(store, lambda: _ret(Broken())).recall("tablas", None)
    assert not found.semantic and found.hits and found.hits[0].by == ["words"]


async def test_editing_a_memory_re_indexes_it(store):
    service = MemoryService(store, lambda: _ret(ConceptEmbedder()))
    m = store.add("El perro se llama Toby", "fact")
    await service.index()
    store.update(m.id, "El coche es azul")
    assert store.pending("concepts-v1")  # the new text needs a new vector
    await service.index()
    assert (await service.recall("automóvil", None)).hits[0].memory.id == m.id
    assert not store.search("perro Toby", [GLOBAL])


async def test_deleting_removes_text_words_and_vectors_from_the_file(store, tmp_path):
    service = MemoryService(store, lambda: _ret(ConceptEmbedder()))
    keep = store.add("Dato que se queda", "fact")
    secret = store.add("Mi contraseña del banco es zanahoriasecreta42", "fact")
    await service.index()
    assert store.search("zanahoriasecreta42", [GLOBAL])
    assert store.delete(secret.id)
    assert not store.search("zanahoriasecreta42", [GLOBAL])
    db = store._db
    assert db.execute("SELECT COUNT(*) FROM chunks WHERE memory_id = ?", (secret.id,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'zanahoriasecreta42'").fetchone()[0] == 0
    assert b"zanahoriasecreta42" not in (tmp_path / "memory.db").read_bytes()
    assert store.get(keep.id) is not None


def test_prompt_stays_within_the_budget_and_rules_come_first(store):
    for i in range(40):
        store.add(f"Regla {i}: " + "responde con detalle " * 10, "rule")
        store.add(f"Nota {i} sobre el proyecto Atlas: " + "contexto largo " * 80, "fact")
    recall = Recall(rules=store.rules([GLOBAL]), hits=store.search("proyecto Atlas", [GLOBAL], k=6))
    for budget in (200, 600, 1500):
        prompt = memory_prompt(recall, budget)
        assert estimate_tokens(prompt) <= budget + 40, budget
        rules_part = prompt.split("# What you remember")[0]
        assert estimate_tokens(rules_part) <= budget // 2 + 30
    assert prompt.index("standing rules") < prompt.index("What you remember")
    assert memory_prompt(Recall(), 1000) == ""


def test_export_import_round_trip(store, tmp_path):
    store.add("Decisión A", "decision")
    store.add("Archivo", "document", scope="project:p1", source="file:a.md")
    data = store.export()
    other = MemoryStore(tmp_path / "other.db")
    assert other.import_items(data) == 2
    assert sorted(m.text for m in other.list()) == ["Archivo", "Decisión A"]
    assert other.import_items(data) == 2 and len(other.list()) == 3  # a source replaces; plain notes add
    with pytest.raises(ValueError):
        other.import_items([{"text": "x", "kind": "nope"}])
    other.close()


# ------------------------------------------------------------------------------------------- real embeddings
BINARY = find_binary()


@pytest.mark.skipif(BINARY is None, reason="llama-server not installed")
async def test_real_llama_server_embeddings_fill_the_vector_index(tmp_path, store):
    import subprocess
    import sys

    subprocess.run([sys.executable, "tests/fixtures/make_tiny_gguf.py", str(tmp_path)], check=True, capture_output=True)
    server = LlamaServer(ServerConfig(model=tmp_path / "spike-tiny.gguf", port=8791, context=512, kv_cache_type="f16",
                                      extra_args=["--embedding", "--pooling", "last"]))
    await server.start(timeout_s=60)
    try:
        embedder = Embedder(server.base_url, model="spike-tiny.gguf", batch=4)
        service = MemoryService(store, lambda: _ret(embedder))
        for i in range(6):
            store.add(f"nota número {i} sobre el tema {i}", "fact")
        assert await service.index() == 6
        assert store.stats()["embedded"] == 6
        found = await service.recall("tema", None)
        assert found.semantic and found.hits  # random weights: only the plumbing is checked, not the ranking
    finally:
        await server.stop()


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


def events_of(r):
    return [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]


def test_memory_api_crud_search_export_and_clear(api):
    client, state, _ = api
    a = client.post("/api/memory", json={"text": "Usamos PostgreSQL para facturación", "kind": "decision"}).json()
    client.post("/api/memory", json={"text": "Responde siempre en español", "kind": "rule"})
    assert client.post("/api/memory", json={"text": "x", "kind": "nope"}).status_code == 400
    assert client.post("/api/memory", json={"text": "x", "scope": "project:missing"}).status_code == 400
    assert [m["text"] for m in client.get("/api/memory?q=facturacion").json()] == ["Usamos PostgreSQL para facturación"]
    assert client.put(f"/api/memory/{a['id']}", json={"text": "Usamos SQLite"}).json()["text"] == "Usamos SQLite"
    assert client.get("/api/memory?q=postgresql").json() == []
    assert len(client.get("/api/memory?kind=rule").json()) == 1
    status = client.get("/api/memory-status").json()
    assert status["stats"]["memories"] == 2 and status["semantic"]["installed"] is False
    assert status["semantic"]["install"] == "spike models pull qwen3-embedding-0.6b"
    exported = client.get("/api/memory-export")
    assert exported.headers["content-disposition"].startswith("attachment")
    assert client.delete("/api/memory?scope=all").json()["deleted"] == 2
    assert client.post("/api/memory-import", content=exported.content).json()["imported"] == 2
    assert client.delete(f"/api/memory/{a['id']}").status_code == 404  # imported copies get new ids
    assert client.post("/api/memory-import", content=b"[{\"text\": 1}]").status_code == 400


def test_chat_recalls_rules_and_matching_notes(api):
    client, state, local = api
    client.post("/api/memory", json={"text": "Responde siempre con una tabla al final", "kind": "rule"})
    client.post("/api/memory", json={"text": "El cliente Norte paga a 60 días", "kind": "fact"})
    client.post("/api/memory", json={"text": "El perro se llama Toby", "kind": "fact"})
    local._script = [text("ok")]
    events = events_of(client.post("/api/chat", json={"message": "¿A cuántos días paga el cliente Norte?"}))
    system = local.requests[-1].messages[0].content
    assert "Responde siempre con una tabla al final" in system and "paga a 60 días" in system
    assert "Toby" not in system
    memory_event = next(e for e in events if e["type"] == "memory")
    assert memory_event["rules"] == 1 and [n["preview"] for n in memory_event["notes"]] == ["El cliente Norte paga a 60 días"]
    conv = client.get(f"/api/conversations/{events[0]['id']}").json()
    assert conv["messages"][-1]["meta"]["memory"]["rules"] == 1

    state.update_settings({"memory": {"enabled": False, "embeddings": "auto", "auto_summary": True}})
    local._script = [text("ok")]
    events = events_of(client.post("/api/chat", json={"message": "¿A cuántos días paga el cliente Norte?"}))
    assert "60 días" not in local.requests[-1].messages[0].content and not any(e["type"] == "memory" for e in events)


def test_project_files_become_project_memory(api):
    client, state, local = api
    pid = client.post("/api/projects", json={"name": "Tesis"}).json()["id"]
    r = client.put(f"/api/projects/{pid}/files/notas/fuentes.md", content="La guía ESC 2024 recomienda IECA o ARA-II.".encode())
    assert r.json()["indexed"] is True
    assert client.put(f"/api/projects/{pid}/files/foto.bin", content=b"\x00\x01").json()["indexed"] is False
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "¿Qué recomienda la guía ESC?", "project_id": pid})
    assert "[file notas/fuentes.md" in local.requests[-1].messages[0].content
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "¿Qué recomienda la guía ESC?"})  # outside the project
    assert "IECA" not in local.requests[-1].messages[0].content
    client.delete(f"/api/projects/{pid}/files/notas/fuentes.md")
    assert client.get(f"/api/memory?scope=project:{pid}").json() == []
    client.put(f"/api/projects/{pid}/files/b.md", content=b"otro archivo")
    client.delete(f"/api/projects/{pid}")
    assert state.memory.store.stats()["memories"] == 0


def test_remember_tool_asks_first_and_saves_in_the_project(api):
    client, state, local = api
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    assert state.tools_for(pid).get("remember").default_policy == "ask"
    state.update_settings({"tool_policies": {"remember": "allow"}})
    local._script = [call("remember", {"text": "El plazo de entrega es el 3 de noviembre", "kind": "fact"}), text("ok")]
    client.post("/api/chat", json={"message": "apunta el plazo", "project_id": pid, "mode": "core"})
    saved = client.get(f"/api/memory?scope=project:{pid}").json()
    assert [m["text"] for m in saved] == ["El plazo de entrega es el 3 de noviembre"] and saved[0]["meta"]["by"] == "model"


async def test_chats_are_summarised_into_memory_only_with_local_models(api):
    import time

    client, state, local = api
    state.update_settings({"memory": {"enabled": True, "embeddings": "auto", "auto_summary": False}})
    local._script = [text("ok")] * 3
    cid = None
    for i in range(3):
        r = client.post("/api/chat", json={"message": f"mensaje {i}", **({"conversation_id": cid} if cid else {})})
        cid = events_of(r)[0]["id"]
    assert await state.maybe_summarize(cid) is False  # switched off
    state.update_settings({"memory": {"enabled": True, "embeddings": "auto", "auto_summary": True}})
    local._script = [text("- El usuario prepara la tesis sobre hipertensión")]
    assert await state.maybe_summarize(cid) is True
    summary = state.memory.store.find_source(GLOBAL, f"conversation:{cid}")
    assert summary.kind == "summary" and "tesis" in summary.text and summary.meta["messages"] == 6
    assert local.requests[-1].messages[0].content.startswith("You keep SPIKE's long-term memory")
    assert await state.maybe_summarize(cid) is False  # nothing new since the last summary

    # the chat itself schedules the next summary once six more messages exist
    local._script = [text("ok")] * 3 + [text("- Ahora también estudia la diabetes")]
    for i in range(3):
        client.post("/api/chat", json={"message": f"más {i}", "conversation_id": cid})
    for _ in range(50):
        if "diabetes" in state.memory.store.find_source(GLOBAL, f"conversation:{cid}").text:
            break
        client.get("/api/health")  # lets the server's loop run the background task
        time.sleep(0.02)
    assert state.memory.store.find_source(GLOBAL, f"conversation:{cid}").meta["messages"] == 12

    local.config.local = False  # a paid API never gets asked for a summary
    local._script = [text("ok")] * 3
    calls = len(local.requests)
    for i in range(3):
        client.post("/api/chat", json={"message": f"otra {i}", "conversation_id": cid})
    assert await state.maybe_summarize(cid) is False
    assert len(local.requests) == calls + 3
