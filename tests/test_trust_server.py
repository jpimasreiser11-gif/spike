"""Trustworthy answers through the server: the trust event kept with the message, the settings, and the second opinion
(offered only for a low-confidence answer, sent only after the click, through the provider's guard and the privacy
setting)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.providers.openai_compat import OpenAICompatProvider
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text

SECRET = "ZX-ALBATROS-9931"
FILE = f"Proyecto Albatros\nEl código de acceso del proyecto Albatros es {SECRET}.\n"
WEAK = ("El modelo Zorvak tiene 12 capas. Fue entrenado en 2019 con 40 GPUs. Su latencia media es de 35 ms. "
        "Cuesta 300 euros al mes.")
OPINION = "Segunda opinión: parece correcto, salvo el precio."


def sse(*objs) -> bytes:
    return "".join(f"data: {o if isinstance(o, str) else json.dumps(o)}\n\n" for o in objs).encode()


class Remote:
    """A fake OpenAI-compatible API that answers with a fixed text and keeps every request body it receives."""

    def __init__(self, usage: bool = True):
        self.bodies: list[str] = []
        self.usage = usage
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content.decode())
        if self.fail:
            return httpx.Response(500, text="boom")
        chunks = [{"choices": [{"index": 0, "delta": {"content": OPINION}, "finish_reason": None}]},
                  {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
        if self.usage:
            chunks.append({"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})
        return httpx.Response(200, content=sse(*chunks, "[DONE]"), headers={"content-type": "text/event-stream"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    remote = Remote()
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        if cfg.kind == "openai":
            return OpenAICompatProvider(cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(remote)))
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")  # creates the local provider
    return client, state, remote, scripts


def add_remote(client, **extra):
    """The user's own API provider: it has a key, may bill (allowed) and has prices, so a second opinion has a cost."""
    body = {"preset": "openai", "api_key": "sk-test", "model": "gpt-test", "allow_paid": True,
            "limits": {"price_in": 2.0, "price_out": 10.0}, **extra}
    r = client.post("/api/providers", json=body)
    assert r.status_code == 200, r.text


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def chat(client, scripts, answer=WEAK, message="Háblame del modelo Zorvak", **extra):
    scripts["spike-local"]._script = [text(answer)]
    return events_of(client.post("/api/chat", json={"message": message, "mode": "core", "provider_id": "spike-local",
                                                    **extra}))


def stored(client, evs) -> tuple[dict, dict]:
    """(the user message's id, the assistant message) of the chat the events belong to."""
    conv = next(e for e in evs if e["type"] == "conversation")
    msgs = client.get(f"/api/conversations/{conv['id']}").json()["messages"]
    return conv["user_message_id"], next(m for m in msgs if m["role"] == "assistant")


def project_with_file(client) -> str:
    pid = client.post("/api/projects", json={"name": "Albatros"}).json()["id"]
    r = client.put(f"/api/projects/{pid}/files/notas.txt", content=FILE.encode())
    assert r.status_code == 200 and r.json()["indexed"], r.text
    return pid


def test_trust_event_and_stored_labels(env):
    client, _, _, scripts = env
    evs = chat(client, scripts)
    kinds = [e["type"] for e in evs]
    assert kinds.index("trust") == kinds.index("done") - 1
    trust = next(e for e in evs if e["type"] == "trust")
    assert trust["counts"] == {"verified": 0, "hypothesis": 0, "unchecked": 4}
    assert [c["label"] for c in trust["claims"]] == ["unchecked"] * 4
    _, answer = stored(client, evs)
    assert answer["meta"]["trust"]["counts"] == trust["counts"]
    assert answer["meta"]["trust"]["claims"][0]["text"].startswith("El modelo Zorvak tiene 12 capas")
    assert "escalation" not in trust  # no API provider is configured: nothing to offer
    assert not any(e["type"] == "trust" for e in answer["meta"]["events"])  # kept once, not twice


def test_trust_off_adds_nothing(env):
    client, _, _, scripts = env
    assert client.put("/api/settings", json={"trust": {"enabled": False}}).json()["trust"]["enabled"] is False
    evs = chat(client, scripts)
    assert not any(e["type"] == "trust" for e in evs)
    assert "trust" not in stored(client, evs)[1]["meta"]


def test_trust_settings_are_validated(env):
    client, *_ = env
    assert client.get("/api/settings").json()["trust"] == {
        "enabled": True, "escalate": True, "escalate_unchecked": 3, "model_pass": False}
    for bad in ({"escalate_unchecked": 0}, {"escalate_unchecked": 51}, {"escalate_unchecked": 2.5},
                {"escalate_unchecked": True}, {"enabled": "yes"}, {"colour": "red"}):
        r = client.put("/api/settings", json={"trust": bad})
        assert r.status_code == 400, bad
    assert client.put("/api/settings", json={"trust": "on"}).status_code == 400
    r = client.put("/api/settings", json={"trust": {"escalate_unchecked": 5}})
    assert r.json()["trust"] == {"enabled": True, "escalate": True, "escalate_unchecked": 5, "model_pass": False}


def test_only_the_app_s_chats_are_labelled(env):
    """/v1, MCP and the CLI build their options from the same settings and must not get claim labels (or the extra
    model call of the model pass)."""
    _, state, _, _ = env
    assert state.options("auto").trust is False and state.options("auto").trust_model_pass is False


def test_no_offer_without_an_api_provider(env):
    client, _, _, scripts = env
    evs = chat(client, scripts)
    assert next(e for e in evs if e["type"] == "trust").get("escalation") is None


def test_offer_has_the_cost_from_the_price_settings_and_nothing_is_sent(env):
    client, _, remote, scripts = env
    add_remote(client)
    evs = chat(client, scripts)
    offer = next(e for e in evs if e["type"] == "trust")["escalation"]
    assert offer["status"] == "offered" and offer["reasons"] == ["unchecked"]
    assert offer["unchecked"] == 4 and offer["threshold"] == 3
    [o] = offer["offers"]
    assert o["provider_id"] == "openai" and o["name"] == "OpenAI" and o["blocked"] is None and o["files"] == "none"
    expected = (o["tokens_in"] * 2.0 + o["tokens_out"] * 10.0) / 1e6
    assert o["cost"] == pytest.approx(expected, abs=1e-6) and o["cost"] > 0
    assert remote.bodies == []  # the offer is not a request
    assert stored(client, evs)[1]["meta"]["trust"]["escalation"] == offer


def test_a_failed_checker_makes_an_answer_low_confidence_whatever_the_unchecked_count(env):
    client, state, remote, _ = env
    add_remote(client)
    trust = {"counts": {"verified": 3, "hypothesis": 0, "unchecked": 0}, "verifier_failed": True, "private": False,
             "claims": []}
    offer = state.escalation_offer(trust, set(), "una pregunta", "una respuesta")
    assert offer["reasons"] == ["verifier"] and [o["provider_id"] for o in offer["offers"]] == ["openai"]
    assert state.escalation_offer({**trust, "verifier_failed": False}, set(), "p", "r") is None
    assert state.escalation_offer(trust, {"openai"}, "p", "r") is None  # a provider the run used is not offered again
    assert remote.bodies == []


def test_offer_without_prices_has_no_cost(env):
    client, _, remote, scripts = env
    add_remote(client, limits={})
    offer = next(e for e in chat(client, scripts) if e["type"] == "trust")["escalation"]
    assert offer["offers"][0]["cost"] is None and remote.bodies == []


def test_threshold_decides_the_offer(env):
    client, _, _, scripts = env
    add_remote(client)
    client.put("/api/settings", json={"trust": {"escalate_unchecked": 5}})
    assert next(e for e in chat(client, scripts) if e["type"] == "trust").get("escalation") is None
    client.put("/api/settings", json={"trust": {"escalate_unchecked": 4}})
    assert next(e for e in chat(client, scripts) if e["type"] == "trust")["escalation"]["offers"]
    client.put("/api/settings", json={"trust": {"escalate_unchecked": 1, "escalate": False}})
    assert next(e for e in chat(client, scripts) if e["type"] == "trust").get("escalation") is None


def test_click_sends_one_request_and_keeps_the_answer(env):
    client, _, remote, scripts = env
    add_remote(client)
    evs = chat(client, scripts)
    mid, _ = stored(client, evs)
    assert remote.bodies == []
    r = client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"})
    assert r.status_code == 200, r.text
    assert len(remote.bodies) == 1  # exactly one call, made by the click
    body = json.loads(remote.bodies[0])
    sent = "\n".join(m["content"] for m in body["messages"])
    assert "Háblame del modelo Zorvak" in sent and "tiene 12 capas" in sent  # the question, answer and claims
    answer = r.json()["answer"]
    assert r.json()["status"] == "answered"
    assert answer["text"] == OPINION and answer["provider_id"] == "openai" and not answer["estimated"]
    assert answer["tokens_in"] == 1000 and answer["tokens_out"] == 200
    assert answer["cost"] == pytest.approx((1000 * 2.0 + 200 * 10.0) / 1e6)
    assert stored(client, evs)[1]["meta"]["trust"]["escalation"]["answer"]["text"] == OPINION
    log = client.get("/api/calls?remote=true").json()
    assert [c["status"] for c in log] == ["ok"] and log[0]["provider_id"] == "openai"
    # a second click does not ask again (and does not spend again)
    assert client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"}).status_code == 409
    assert len(remote.bodies) == 1


def test_a_request_in_flight_blocks_a_second_click(env):
    client, state, remote, scripts = env
    add_remote(client)
    mid, answer = stored(client, chat(client, scripts))
    state.asking.add(answer["id"])  # what the first click leaves while it waits
    r = client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"})
    assert r.status_code == 409 and "being asked" in r.json()["detail"] and remote.bodies == []


def test_answer_without_an_offer_cannot_be_escalated(env):
    client, _, remote, scripts = env
    add_remote(client)
    client.put("/api/settings", json={"trust": {"escalate_unchecked": 9}})
    mid, _ = stored(client, chat(client, scripts))
    assert client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"}).status_code == 400
    assert client.post("/api/messages/nope/escalate", json={"provider_id": "openai"}).status_code == 404
    assert remote.bodies == []


def test_only_external_providers_with_a_key(env):
    client, _, remote, scripts = env
    add_remote(client)
    mid, _ = stored(client, chat(client, scripts))
    for pid in ("spike-local", "nope"):
        assert client.post(f"/api/messages/{mid}/escalate", json={"provider_id": pid}).status_code == 400
    assert remote.bodies == []


def test_paid_call_guard_applies(env):
    client, _, remote, scripts = env
    add_remote(client)
    mid, _ = stored(client, chat(client, scripts))
    client.patch("/api/providers/openai", json={"allow_paid": False})
    r = client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"})
    assert r.status_code == 403 and "may bill your account" in r.json()["detail"]
    assert remote.bodies == []
    client.patch("/api/providers/openai", json={"allow_paid": True})  # allowed again: the same offer still works
    assert client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"}).status_code == 200


def test_blocked_provider_is_shown_in_the_offer(env):
    client, _, remote, scripts = env
    add_remote(client, allow_paid=False)
    offer = next(e for e in chat(client, scripts) if e["type"] == "trust")["escalation"]
    assert "may bill your account" in offer["offers"][0]["blocked"] and remote.bodies == []


def test_monthly_limit_applies(env):
    client, state, remote, scripts = env
    add_remote(client, limits={"price_in": 2.0, "price_out": 10.0, "monthly_tokens": 1000})
    mid, _ = stored(client, chat(client, scripts))
    state.store.log_call(provider_id="openai", provider="OpenAI", status="ok", tokens_in=900, tokens_out=150)
    r = client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"})
    assert r.status_code == 403 and "monthly limit is reached" in r.json()["detail"]
    assert remote.bodies == []


def test_failed_request_can_be_asked_again(env):
    client, _, remote, scripts = env
    add_remote(client)
    mid, _ = stored(client, chat(client, scripts))
    remote.fail = True
    r = client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"})
    assert r.status_code == 502, r.text
    remote.fail = False
    assert client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"}).status_code == 200


def private_chat(client, scripts, pid):
    client.put("/api/settings", json={"tool_policies": {"read_file": "allow"}, "trust": {"escalate_unchecked": 1}})
    scripts["spike-local"]._script = [call("read_file", {"path": "notas.txt"}),
                                      text(f"El código de acceso es {SECRET}. El proyecto tiene 12 empleados.")]
    return events_of(client.post("/api/chat", json={
        "message": "Lee notas.txt y dime el código de acceso del proyecto Albatros", "mode": "core",
        "provider_id": "spike-local", "project_id": pid}))


def test_privacy_setting_is_respected(env):
    client, _, remote, scripts = env
    add_remote(client)
    pid = project_with_file(client)
    evs = private_chat(client, scripts, pid)
    trust = next(e for e in evs if e["type"] == "trust")
    assert trust["private"] is True and trust["counts"]["verified"] == 1 and trust["counts"]["unchecked"] == 1
    [o] = trust["escalation"]["offers"]
    assert o["files"] == "withheld"  # the offer says the files would not go
    mid, _ = stored(client, evs)
    r = client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"})
    assert r.status_code == 200, r.text
    assert len(remote.bodies) == 1 and SECRET not in remote.bodies[0]
    assert "file content withheld" in remote.bodies[0]
    assert r.json()["answer"]["files_withheld"] >= 1
    log = client.get("/api/calls?remote=true").json()
    assert log[0]["files_withheld"] >= 1 and log[0]["files_sent"] == 0


def test_with_files_allowed_they_are_sent(env):
    """The control for the test above: the same check does see the secret once the user allows files."""
    client, _, remote, scripts = env
    add_remote(client, share_files=True)
    pid = project_with_file(client)
    evs = private_chat(client, scripts, pid)
    [o] = next(e for e in evs if e["type"] == "trust")["escalation"]["offers"]
    assert o["files"] == "sent"
    mid, _ = stored(client, evs)
    assert client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"}).status_code == 200
    assert SECRET in remote.bodies[0]
    assert client.get("/api/calls?remote=true").json()[0]["files_sent"] >= 1


def test_temporary_chat_can_ask_too(env):
    client, _, remote, scripts = env
    add_remote(client)
    evs = chat(client, scripts, temporary=True)
    assert next(e for e in evs if e["type"] == "trust")["escalation"]["offers"]
    mid = next(e for e in evs if e["type"] == "conversation")["user_message_id"]
    assert client.post(f"/api/messages/{mid}/escalate", json={"provider_id": "openai"}).status_code == 200
    assert len(remote.bodies) == 1
