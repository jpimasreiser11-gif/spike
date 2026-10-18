import json

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    return TestClient(create_app(state)), state, scripts


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_health_system_specialists(env):
    client, _, _ = env
    assert client.get("/api/health").json()["ok"]
    sysinfo = client.get("/api/system").json()
    assert sysinfo["hardware"]["total_ram_gb"] > 0 and sysinfo["secrets_backend"] == "file-0600"
    specs = client.get("/api/specialists").json()
    assert {s["id"] for s in specs} >= {"core", "finance", "medicine"}


def test_provider_crud_keeps_keys_out_of_db(env, tmp_path):
    client, state, _ = env
    r = client.post("/api/providers", json={"preset": "deepseek", "api_key": "sk-secret", "model": "deepseek-chat"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_key"] and body["paid"] and not body["allow_paid"] and "api_key" not in body
    assert b"sk-secret" not in (tmp_path / "spike.db").read_bytes()
    assert state.secrets.get("provider:deepseek") == "sk-secret"
    assert client.patch("/api/providers/deepseek", json={"allow_paid": True}).json()["allow_paid"] is True
    assert client.post("/api/providers", json={"preset": "deepseek"}).status_code == 409
    assert client.delete("/api/providers/deepseek").json()["ok"]
    assert state.secrets.get("provider:deepseek") is None
    assert client.delete("/api/providers/spike-local").status_code == 400


def test_chat_streams_and_persists(env):
    client, _, scripts = env
    client.get("/api/providers")  # instantiate providers
    scripts["spike-local"]._script = [text("Hola ", "joan")]
    r = client.post("/api/chat", json={"message": "Hola, ¿qué tal?"})
    evs = events_of(r)
    assert evs[0]["type"] == "conversation"
    assert [e["type"] for e in evs][-1] == "done" and evs[-1]["text"] == "Hola joan"
    conv = client.get(f"/api/conversations/{evs[0]['id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["meta"]["route"]["mode"] == "direct"
    # follow-up includes history
    scripts["spike-local"]._script = [text("ok")]
    client.post("/api/chat", json={"message": "y ahora?", "conversation_id": evs[0]["id"]})
    req = scripts["spike-local"].requests[-1]
    assert [m.content for m in req.messages if m.role != "system"] == ["Hola, ¿qué tal?", "Hola joan", "y ahora?"]


def test_custom_instructions_reach_the_model(env):
    client, _, scripts = env
    client.get("/api/providers")
    client.put("/api/settings", json={"custom_instructions": "Siempre responde en español."})
    scripts["spike-local"]._script = [text("vale")]
    client.post("/api/chat", json={"message": "Explain EBITDA", "mode": "finance"})
    system = scripts["spike-local"].requests[-1].messages[0].content
    assert "Spike Finance" in system and "Siempre responde en español." in system
    assert client.put("/api/settings", json={"nope": 1}).status_code == 400


def test_chat_with_permissioned_tool_and_decision_endpoint(env, tmp_path):
    client, state, scripts = env
    client.get("/api/providers")
    # write_file asks for permission; deny it via policy to keep the test synchronous
    client.put("/api/settings", json={"tool_policies": {"write_file": "deny"}})
    scripts["spike-local"]._script = [call("write_file", {"path": "a.txt", "content": "x"}), text("could not write")]
    evs = events_of(client.post("/api/chat", json={"message": "write a file", "mode": "core"}))
    result = next(e for e in evs if e["type"] == "tool_result")
    assert result["ok"] is False and "disabled" in result["content"]
    assert not (tmp_path / "ws" / "a.txt").exists()
    assert client.post("/api/permissions/nope", json={"decision": "allow_once"}).status_code == 404


def test_unknown_mode_and_provider_rejected(env):
    client, _, _ = env
    assert client.post("/api/chat", json={"message": "x", "mode": "astrology"}).status_code == 400
    assert client.post("/api/chat", json={"message": "x", "provider_id": "nope"}).status_code == 400


def test_runtime_start_without_model_is_explained(env):
    client, _, _ = env
    r = client.post("/api/runtime/start")
    assert r.status_code == 400 and "No local model configured" in r.json()["detail"]


def test_retry_and_edit_replace_the_rest_of_the_chat(env):
    client, state, scripts = env
    client.get("/api/providers")
    scripts["spike-local"]._script = [text("primera"), text("segunda"), text("editada")]
    first = events_of(client.post("/api/chat", json={"message": "hola"}))
    conv = next(e for e in first if e["type"] == "conversation")
    cid, uid = conv["id"], conv["user_message_id"]
    retry = events_of(client.post("/api/chat", json={"message": "hola", "conversation_id": cid, "replace_from": uid}))
    assert retry[-1]["type"] == "done" and retry[-1]["text"] == "segunda"
    assert [(m["role"], m["content"]) for m in state.store.messages(cid)] == [("user", "hola"), ("assistant", "segunda")]
    assert [m.content for m in scripts["spike-local"].requests[1].messages if m.role != "system"] == ["hola"]
    uid = next(e for e in retry if e["type"] == "conversation")["user_message_id"]
    events_of(client.post("/api/chat", json={"message": "hola otra vez", "conversation_id": cid, "replace_from": uid}))
    assert [m["content"] for m in state.store.messages(cid)] == ["hola otra vez", "editada"]
    assistant = state.store.messages(cid)[1]["id"]
    for bad in ({"replace_from": assistant, "conversation_id": cid}, {"replace_from": "nope", "conversation_id": cid},
                {"replace_from": uid}):
        assert client.post("/api/chat", json={"message": "x", **bad}).status_code == 400
    assert len(state.store.list_conversations()) == 1  # a refused retry creates no chat


def test_an_edit_can_go_on_in_a_branch_and_the_original_stays(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([text("uno"), text("dos"), text("dos bis")], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    client = TestClient(create_app(AppState(home=tmp_path, provider_factory=factory)))
    client.get("/api/providers")

    def send(message, cid=None):
        body = {"message": message, "mode": "core", **({"conversation_id": cid} if cid else {})}
        lines = client.post("/api/chat", json=body).text.splitlines()
        return next(json.loads(x[6:]) for x in lines if x.startswith("data: ") and '"conversation"' in x)

    cid = send("primera")["id"]
    second = send("segunda", cid)["user_message_id"]
    branch = client.post(f"/api/conversations/{cid}/branch", json={"before": second, "title": "Rama"}).json()
    assert branch["title"] == "Rama" and branch["id"] != cid and branch["temporary"] is False
    copied = client.get(f"/api/conversations/{branch['id']}").json()["messages"]
    assert [(m["role"], m["content"]) for m in copied] == [("user", "primera"), ("assistant", "uno")]

    send("segunda, mejor así", branch["id"])
    assert [m.content for m in local.requests[-1].messages[1:]] == ["primera", "uno", "segunda, mejor así"]
    original = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert [m["content"] for m in original] == ["primera", "uno", "segunda", "dos"]
    assert client.post(f"/api/conversations/{cid}/branch", json={"before": original[1]["id"]}).status_code == 400


def test_a_specialist_can_ask_the_user_and_go_on_with_the_answer(tmp_path, monkeypatch):
    import threading

    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([call("ask_user", {"question": "¿Para qué país es la factura?",
                                                "options": ["España", "Francia"]}),
                              text("Entonces el IVA es del 21 %.")], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.__enter__()  # one event loop for both requests, as under uvicorn
    client.get("/api/providers")
    seen: list[dict] = []

    def answer_when_asked():
        for _ in range(200):
            if state.broker.questions:
                qid = next(iter(state.broker.questions))
                assert client.post(f"/api/questions/{qid}", json={"answer": "España"}).json() == {"ok": True}
                return
            threading.Event().wait(0.02)

    helper = threading.Thread(target=answer_when_asked)
    helper.start()
    with client.stream("POST", "/api/chat", json={"message": "¿Qué IVA pongo?", "mode": "core"}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]))
    helper.join()
    question = next(e for e in seen if e["type"] == "question")
    assert question["question"] == "¿Para qué país es la factura?" and question["options"] == ["España", "Francia"]
    assert next(e for e in seen if e["type"] == "answered")["answer"] == "España"
    assert local.requests[-1].messages[-1].content == "The user answered: España"
    cid = next(e["id"] for e in seen if e["type"] == "conversation")
    meta = [m for m in state.store.messages(cid) if m["role"] == "assistant"][0]["meta"]
    assert meta["questions"] == [{"id": question["id"], "question": "¿Para qué país es la factura?",
                                  "options": ["España", "Francia"], "answer": "España"}]
    assert client.post("/api/questions/ask_nope", json={"answer": "x"}).status_code == 404
    client.__exit__(None, None, None)


async def test_nobody_to_ask_through_the_api():
    from spike.agent.loop import AgentRun, run_agent
    from spike.tools.base import HeadlessBroker, PermissionBroker
    from spike.tools.builtin import AskUser

    provider = ScriptedProvider([call("ask_user", {"question": "¿País?"}), text("Asumo España.")])
    events = [ev async for ev in run_agent(provider, [], tools=[AskUser()], broker=HeadlessBroker(PermissionBroker()),
                                                run=AgentRun())]
    result = next(e for e in events if e["type"] == "tool_result")
    assert not result["ok"] and "best assumption" in result["content"]
    assert not any(e["type"] == "question" for e in events)


def test_an_answer_contract_in_the_app_gives_checked_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([text('{"pais": "España"'), text('{"pais": "España", "iva": 21}')], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")
    schema = {"type": "object", "properties": {"pais": {"type": "string"}, "iva": {"type": "number"}},
              "required": ["pais", "iva"]}
    lines = client.post("/api/chat", json={"message": "IVA general de España", "response_schema": schema}).text
    events = [json.loads(x[6:]) for x in lines.splitlines() if x.startswith("data: ")]
    contract = next(e for e in events if e["type"] == "contract")
    assert contract["valid"] and contract["attempts"] == 2
    done = next(e for e in events if e["type"] == "done")
    assert json.loads(done["text"]) == {"pais": "España", "iva": 21} and len(done["specialists"]) == 1
    assert local.requests[0].json_schema == schema and local.requests[0].tools == []
    assert "not valid JSON" in local.requests[1].messages[-1].content
    cid = next(e["id"] for e in events if e["type"] == "conversation")
    meta = [m for m in state.store.messages(cid) if m["role"] == "assistant"][0]["meta"]
    assert meta["contract"] == {"valid": True, "attempts": 2, "errors": []}
    bad = client.post("/api/chat", json={"message": "x", "response_schema": {"type": 5}})
    assert bad.status_code == 400 and "invalid JSON Schema" in bad.json()["detail"]
