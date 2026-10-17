"""Evolution level 1: "recuerda que…" is saved at once, a correction becomes a rule once the user approves it, and
both shape later chats."""

import json

import pytest
from fastapi.testclient import TestClient

from spike.memory.learn import correction_rule, explicit_memories
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text


@pytest.mark.parametrize(("message", "expected"), [
    ("Recuerda que mi empresa se llama Acme. ¿Qué IVA aplico?", [("Mi empresa se llama Acme.", "fact")]),
    ("a partir de ahora respóndeme en catalán", [("A partir de ahora respóndeme en catalán", "rule")]),
    ("Hola. Recuerda que nunca uses emojis.", [("Nunca uses emojis.", "rule")]),
    ("recuerda: no uses emojis", [("No uses emojis", "rule")]),
    ("recuerda que prefiero tablas a listas", [("Prefiero tablas a listas", "preference")]),
    ("Please remember: always cite the source", [("Always cite the source", "rule")]),
    ("Remember that I work in Madrid", [("I work in Madrid", "fact")]),
    ("from now on, answer in English.", [("From now on, answer in English.", "rule")]),
    ("no vuelvas a inventarte cifras", [("No vuelvas a inventarte cifras", "rule")]),
    ("¿Recuerdas que te dije lo del IVA?", []),
    ("¿Recuerda que hablamos ayer?", []),
    ("recuérdalo", []),
    ("Del 5 en adelante es otra cosa", []),
    ("Explica qué es recordar en psicología", []),
])
def test_explicit_requests_to_remember(message, expected):
    assert [(m.text, m.kind) for m in explicit_memories(message)] == expected


@pytest.mark.parametrize(("message", "expected"), [
    ("No, el IVA general en España es del 21 %, no del 18 %.", "El IVA general en España es del 21 %, no del 18 %."),
    ("Te equivocas: la capital de Australia es Canberra.", "La capital de Australia es Canberra."),
    ("That's wrong, the dose is 500 mg twice a day.", "The dose is 500 mg twice a day."),
    ("Eso no es así. El plazo es de 30 días naturales.", "El plazo es de 30 días naturales."),
    ("No, gracias", None),
    ("No entiendo el paso 3", None),
    ("No, ¿por qué lo dices?", None),
    ("Vale, ahora hazlo en una tabla", None),
])
def test_corrections_become_proposals(message, expected):
    assert correction_rule(message) == expected


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")
    return client, state, local


def chat(client, local, message, cid=None, reply="Vale."):
    local._script = [text(reply)]
    body = {"message": message, "mode": "core", **({"conversation_id": cid} if cid else {})}
    events = [json.loads(line[6:]) for line in client.post("/api/chat", json=body).text.splitlines()
              if line.startswith("data: ")]
    conv = next(e for e in events if e["type"] == "conversation")
    return events, conv["id"], conv["user_message_id"]


def system_prompt(local) -> str:
    return local.requests[-1].messages[0].content


def test_recuerda_que_is_saved_and_shapes_later_chats(env):
    client, state, local = env
    events, _, mid = chat(client, local, "Recuerda que nunca uses emojis. ¿Qué es el IVA?")
    saved = next(e for e in events if e["type"] == "memory_saved")["saved"]
    assert [(s["kind"], s["text"]) for s in saved] == [("rule", "Nunca uses emojis.")]
    assert "# Saved to memory from the user's message just now" in system_prompt(local)
    rules = [m.text for m in state.memory.store.list(kind="rule")]
    assert rules == ["Nunca uses emojis."]

    chat(client, local, "Explícame el IRPF")  # a new chat
    assert "standing rules" in system_prompt(local) and "- Nunca uses emojis." in system_prompt(local)
    assert "Saved to memory from the user's message" not in system_prompt(local)

    _, _, again = chat(client, local, "recuerda que nunca uses emojis")
    assert len(state.memory.store.list(kind="rule")) == 1  # the same rule is not saved twice
    assert client.post(f"/api/messages/{again}/learn", json={"action": "undo", "memory": saved[0]["id"]}).status_code \
        == 404  # it already existed before that message: undo there leaves it alone

    learn = client.post(f"/api/messages/{mid}/learn", json={"action": "undo", "memory": saved[0]["id"]}).json()
    assert learn["saved"][0]["undone"] and state.memory.store.list(kind="rule") == []


def test_a_correction_becomes_a_rule_only_when_the_user_saves_it(env):
    client, state, local = env
    _, cid, _ = chat(client, local, "¿Cuál es el IVA general en España?", reply="Es del 18 %.")
    events, _, mid = chat(client, local, "No, el IVA general en España es del 21 %, no del 18 %.", cid)
    proposal = next(e for e in events if e["type"] == "correction")
    assert proposal["text"] == "El IVA general en España es del 21 %, no del 18 %."
    assert state.memory.store.list(kind="rule") == []  # nothing is saved without the user
    stored = [m for m in state.store.messages(cid) if m["role"] == "assistant"][-1]["meta"]["learn"]
    assert stored["correction"]["status"] == "proposed"

    learn = client.post(f"/api/messages/{mid}/learn",
                        json={"action": "save", "text": "El IVA general en España es del 21 %."}).json()
    assert learn["correction"]["status"] == "saved"
    rule = state.memory.store.get(learn["correction"]["memory"])
    assert rule.kind == "rule" and rule.text == "El IVA general en España es del 21 %." and rule.scope == "global"
    assert rule.meta["from"] == "correction"

    chat(client, local, "Calcula el IVA de 100 €")
    assert "- El IVA general en España es del 21 %." in system_prompt(local)

    learn = client.post(f"/api/messages/{mid}/learn", json={"action": "undo", "memory": rule.id}).json()
    assert learn["correction"]["status"] == "proposed" and state.memory.store.get(rule.id) is None
    assert client.post(f"/api/messages/{mid}/learn", json={"action": "dismiss"}).json()["correction"]["status"] \
        == "dismissed"
    stored = [m for m in state.store.messages(cid) if m["role"] == "assistant"][-1]["meta"]["learn"]
    assert stored["correction"]["status"] == "dismissed"


def test_no_proposal_without_an_answer_to_correct_or_when_learning_is_off(env):
    client, state, local = env
    events, _, mid = chat(client, local, "No, el IVA general en España es del 21 %.")
    assert not any(e["type"] == "correction" for e in events)
    assert client.post(f"/api/messages/{mid}/learn", json={"action": "save"}).status_code == 400
    assert client.post("/api/messages/nope/learn", json={"action": "save"}).status_code == 404

    state.update_settings({"memory": {**state.memory_settings(), "learn": False}})
    events, _, _ = chat(client, local, "Recuerda que mi empresa se llama Acme")
    assert not any(e["type"] == "memory_saved" for e in events) and state.memory.store.list() == []


def test_in_a_project_what_is_learned_stays_in_the_project(env):
    client, state, local = env
    project = client.post("/api/projects", json={"name": "Clínica"}).json()
    local._script = [text("Vale.")]
    body = {"message": "Recuerda que trabajamos con pacientes pediátricos", "mode": "core", "project_id": project["id"]}
    client.post("/api/chat", json=body)
    [memory] = state.memory.store.list(kind="fact")
    assert memory.scope == f"project:{project['id']}"
