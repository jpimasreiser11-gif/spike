"""G40 — Settings review: every persisted setting is validated by the server (a clear 400, never a stored bad
value), survives a restart, and the defaults spend no money, open no network and enable no live trading."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import DEFAULT_SETTINGS, AppState

HOSTS = {"testserver", "127.0.0.1"}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    return tmp_path


@pytest.fixture
def client(home: Path) -> TestClient:
    return TestClient(create_app(AppState(home=home), allowed_hosts=HOSTS), client=("127.0.0.1", 50000))


def put(client: TestClient, **patch):
    return client.put("/api/settings", json=patch)


# ------------------------------------------------------------------ safe defaults
def test_defaults_spend_nothing_and_open_nothing(client: TestClient) -> None:
    s = client.get("/api/settings").json()
    assert s["finance"]["live"]["enabled"] is False and s["finance"]["live"]["sandbox"] is True
    assert s["finance"]["live"]["no_withdrawal"] is False
    assert s["desktop"]["enabled"] is False
    assert s["parallel"] is False
    assert s["evolution"]["training_data"] is False and s["evolution"]["personal_adapter"] is False
    assert s["trust"]["model_pass"] is False
    assert s["default_provider"] == "spike-local"
    assert s["browser"]["unknown"] == "ask"
    assert s["sandbox"] == "auto"
    assert s["tool_policies"] == {}
    assert DEFAULT_SETTINGS["local_runtime"]["port"] == 8737


def test_paid_providers_stay_blocked_until_allowed(client: TestClient) -> None:
    presets = client.get("/api/presets").json()
    paid = next(p for p in presets if p["paid"])
    added = client.post("/api/providers", json={"preset": paid["id"], "api_key": "k"}).json()
    assert added["paid"] is True and added["allow_paid"] is False and added["share_files"] is False
    assert all(not p["allow_paid"] for p in client.get("/api/providers").json())


def test_real_orders_cannot_be_enabled_without_the_setup(client: TestClient) -> None:
    r = put(client, finance={"live": {"enabled": True}})
    assert r.status_code == 400 and "real orders need" in r.json()["detail"]
    assert client.get("/api/settings").json()["finance"]["live"]["enabled"] is False


# ------------------------------------------------------------------ validation
BAD = [
    ("custom_instructions", 5),
    ("custom_instructions", "x" * 20001),
    ("use_planner", "yes"),
    ("parallel", 1),
    ("tools_enabled", None),
    ("reasoning", "true"),
    ("temperature", "hot"),
    ("temperature", -0.1),
    ("temperature", 2.5),
    ("temperature", True),
    ("max_tokens", 10),
    ("max_tokens", 99999),
    ("max_tokens", 100.5),
    ("max_tokens", "2048"),
    ("skill_mode", "everything"),
    ("default_provider", "nope"),
    ("default_provider", 3),
    ("specialist_instructions", {"core": 5}),
    ("specialist_instructions", {"core": "x" * 20001}),
    ("specialist_bindings", {"core": "spike-local"}),
    ("specialist_bindings", {"core": {"provider_id": "nope"}}),
    ("specialist_bindings", {"core": {"other": "x"}}),
    ("tool_policies", {"write_file": "maybe"}),
    ("tool_policies", {"": "allow"}),
    ("memory", {"enabled": "yes"}),
    ("memory", {"embeddings": "gpu"}),
    ("memory", {"surprise": True}),
    ("evolution", {"enabled": 1}),
    ("evolution", {"surprise": True}),
    ("local_runtime", {"context": 3}),
    ("local_runtime", {"context": "big"}),
    ("local_runtime", {"threads": 0}),
    ("local_runtime", {"port": 80}),
    ("local_runtime", {"port": 70000}),
    ("local_runtime", {"kv_cache_type": "q1"}),
    ("local_runtime", {"model": 5}),
    ("local_runtime", {"adapters": "a.gguf"}),
    ("local_runtime", {"surprise": 1}),
    ("disabled_skills", [1]),
    ("disabled_skills", "all"),
    ("sandbox", "maybe"),
]


@pytest.mark.parametrize(("key", "value"), BAD, ids=[f"{k}-{i}" for i, (k, _) in enumerate(BAD)])
def test_bad_values_are_rejected_with_400_and_not_stored(client: TestClient, key: str, value) -> None:
    before = client.get("/api/settings").json()
    r = put(client, **{key: value})
    assert r.status_code == 400, (key, value, r.text)
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]
    assert client.get("/api/settings").json() == before


def test_wrapped_messages_name_the_setting(client: TestClient) -> None:
    assert put(client, temperature=9).json()["detail"].startswith("invalid setting 'temperature'")
    assert put(client, trust={"escalate_unchecked": 0}).json()["detail"].startswith("invalid setting 'trust'")
    assert put(client, desktop={"max_steps": 999}).json()["detail"].startswith("invalid setting 'desktop'")
    assert put(client, sandbox="x").json()["detail"].startswith("invalid setting 'sandbox'")
    assert put(client, default_provider="nope").json()["detail"] == "unknown provider 'nope'"


# ------------------------------------------------------------------ good values persist across a restart
def test_every_control_value_survives_a_restart(client: TestClient, home: Path) -> None:
    other = client.post("/api/providers", json={"id": "mine", "kind": "openai", "base_url": "http://127.0.0.1:9/v1",
                                                "model": "m"})
    assert other.status_code == 200
    good = {
        "custom_instructions": "Responde en español.",
        "specialist_instructions": {"core": "corto"},
        "default_provider": "mine",
        "specialist_bindings": {"core": {"provider_id": "mine"}},
        "tool_policies": {"write_file": "deny"},
        "sandbox": "required",
        "tools_enabled": False,
        "use_planner": False,
        "parallel": True,
        "reasoning": True,
        "temperature": 0.3,
        "max_tokens": 4096,
        "skill_mode": "off",
        "memory": {"enabled": False, "embeddings": "off", "auto_summary": False, "learn": False},
        "trust": {"enabled": True, "escalate": False, "escalate_unchecked": 7, "model_pass": True},
        "disabled_skills": ["x-skill"],
        "evolution": {"enabled": False, "auto_router": False, "training_data": True, "auto_strategy": False,
                      "personal_adapter": True},
        "local_runtime": {"model": "/tmp/m.gguf", "adapters": [], "context": 4096, "threads": 4, "gpu_layers": 0,
                          "kv_cache_type": "f16", "port": 8800},
        "browser": {"domains": {"example.com": "allow"}, "unknown": "ask"},
    }
    r = put(client, **good)
    assert r.status_code == 200, r.text
    again = TestClient(create_app(AppState(home=home), allowed_hosts=HOSTS)).get("/api/settings").json()
    for key, value in good.items():
        assert again[key] == value, key


def test_null_clears_the_optional_numbers(client: TestClient) -> None:
    assert put(client, temperature=0.5, max_tokens=512).status_code == 200
    s = put(client, temperature=None, max_tokens=None, reasoning=None).json()
    assert s["temperature"] is None and s["max_tokens"] is None and s["reasoning"] is None


def test_partial_memory_and_runtime_patches_keep_the_other_keys(client: TestClient) -> None:
    s = put(client, memory={"enabled": False}).json()
    assert s["memory"] == {"enabled": False, "embeddings": "auto", "auto_summary": True, "learn": True}
    s = put(client, local_runtime={"threads": 3}).json()
    assert s["local_runtime"]["threads"] == 3 and s["local_runtime"]["port"] == 8737


# ------------------------------------------------------------------ deleting a provider leaves no dangling choice
def test_removing_a_provider_resets_the_default_and_bindings(client: TestClient) -> None:
    client.post("/api/providers", json={"id": "mine", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"})
    put(client, default_provider="mine", specialist_bindings={"core": {"provider_id": "mine"},
                                                              "code": {"provider_id": "spike-local"}})
    assert client.delete("/api/providers/mine").status_code == 200
    s = client.get("/api/settings").json()
    assert s["default_provider"] == "spike-local"
    assert s["specialist_bindings"] == {"code": {"provider_id": "spike-local"}}


# ------------------------------------------------------------------ providers: limits and fields
def test_provider_limits_and_fields_are_validated(client: TestClient) -> None:
    client.post("/api/providers", json={"id": "mine", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"})
    assert client.patch("/api/providers/mine", json={"limits": {"monthly_tokens": 0}}).status_code == 422
    assert client.patch("/api/providers/mine", json={"limits": {"monthly_cost": -1}}).status_code == 422
    assert client.patch("/api/providers/mine", json={"base_url": "ftp://x"}).status_code == 400
    assert client.patch("/api/providers/mine", json={"name": "x" * 300}).status_code == 422
    bad_id = {"id": "Bad Id", "kind": "openai", "base_url": "http://x"}
    assert client.post("/api/providers", json=bad_id).status_code == 422
