"""G36 export and delete all my data: the double confirmation is enforced by the server, deletion is real, secrets and
models survive unless asked, and the app starts again on the same home."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.test_backup_g34 import CONN, KEY, fill, make_app

JSON = {"content-type": "application/json"}


def tree(home: Path) -> set[str]:
    return {p.relative_to(home).as_posix() for p in home.rglob("*")}


SEEDED = ("checkpoints/c1/file.bin", "logs/llama.log", "desktop/c/shot.png", "prototypes/p/run.json",
          "view-scripts/s.json", "design-systems/d/DESIGN.md", "dev/checkpoints/x", "personal/lora.gguf",
          "finance/paper.db", "tune.json", "workspace/notes.md")


def seed_extras(home: Path) -> None:
    for rel in SEEDED:
        f = home / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("data", encoding="utf-8")


def word(client: TestClient) -> str:
    return client.get("/api/privacy/delete-word").json()["word"]


def test_delete_needs_the_word_shown_on_screen(tmp_path, monkeypatch):
    client = make_app(tmp_path / "home", monkeypatch)
    fill(client)
    before = tree(tmp_path / "home")
    assert client.post("/api/privacy/delete", json={"word": "nope"}).status_code == 400
    assert client.post("/api/privacy/delete", json={}).status_code == 422
    assert client.post("/api/privacy/delete", json={"word": word(client)}, headers={"origin": "http://evil.example"}
                       ).status_code == 403
    assert client.post("/api/privacy/delete", content=b'{"word": "x"}', headers={"content-type": "text/plain"}
                       ).status_code == 415
    assert tree(tmp_path / "home") == before  # nothing was touched


def test_delete_everything_leaves_nothing_but_keeps_secrets_and_models(tmp_path, monkeypatch):
    home = tmp_path / "home"
    client = make_app(home, monkeypatch)
    fill(client)
    seed_extras(home)
    secrets_before = (home / "secrets.json").read_bytes()
    res = client.post("/api/privacy/delete", json={"word": word(client)})
    assert res.status_code == 200 and res.json()["deleted"] >= 1
    assert (home / "models" / "big.gguf").exists()  # models are not data
    assert (home / "secrets.json").read_bytes() == secrets_before  # keys untouched
    # only what a new, empty SPIKE creates on its own may exist: no chats, memory, projects, checkpoints, caches
    fresh = tmp_path / "fresh"
    AppState(home=fresh).store._conn.close()
    top = {p.split("/")[0].removesuffix("-wal").removesuffix("-shm") for p in tree(home)}
    # the workspace folder is recreated empty (SPIKE_WORKSPACE points into this home in the test)
    assert top <= {p.split("/")[0] for p in tree(fresh)} | {"models", "secrets.json", "secret-names.json", "workspace"}, top
    assert not any((home / "workspace").iterdir())
    for rel in SEEDED:
        assert not (home / rel).exists() or (home / rel).read_bytes() != b"data", rel
    for db in ("spike.db", "memory.db", "evolution.db"):  # recreated empty by the running app, no user rows
        assert not (home / db).exists() or b"Backup me" not in (home / db).read_bytes()
    blob = b"".join(p.read_bytes() for p in home.rglob("*") if p.is_file() and not p.name.startswith("secrets")
                    and p.parts[len(home.parts)] != "models")
    for needle in (b"Backup me", b"hello history", b"g34 fact", b"Proj G34", b"project file"):
        assert needle not in blob, needle
    # the running app answers with empty data
    assert client.get("/api/memory").json() == [] and client.get("/api/projects").json() == []


def test_delete_with_models_and_secrets_when_asked(tmp_path, monkeypatch):
    home = tmp_path / "home"
    client = make_app(home, monkeypatch)
    fill(client)
    res = client.post("/api/privacy/delete", json={"word": word(client), "delete_models": True, "delete_secrets": True})
    assert res.status_code == 200
    assert not (home / "models" / "big.gguf").exists()
    assert not (home / "secrets.json").exists() or (KEY not in (home / "secrets.json").read_text()
                                                    and CONN not in (home / "secrets.json").read_text())


def test_app_starts_cleanly_again_on_the_same_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    client = make_app(home, monkeypatch)
    fill(client)
    assert client.post("/api/privacy/delete", json={"word": word(client)}).status_code == 200
    client.app.state.spike.store._conn.close()  # simulate SPIKE being closed and started again
    again = TestClient(create_app(AppState(home=home)), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    assert again.get("/api/projects").status_code == 200
    assert again.post("/api/projects", json={"name": "fresh"}).status_code == 200
    assert os.path.isdir(home)


def test_word_is_single_use(tmp_path, monkeypatch):
    client = make_app(tmp_path / "home", monkeypatch)
    w = word(client)
    assert client.post("/api/privacy/delete", json={"word": w}).status_code == 200
    assert client.post("/api/privacy/delete", json={"word": w}).status_code == 400


class FakeKeychain:
    """Stands in for the OS keychain (`keyring`): SPIKE cannot list it, only get, set and delete by name."""

    def __init__(self):
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        self.data.pop((service, name))


def test_keychain_entries_only_go_with_their_own_checkbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    client = make_app(home, monkeypatch)
    keychain = FakeKeychain()
    client.app.state.spike.secrets._keyring = keychain
    assert client.post("/api/providers", json={"preset": "deepseek", "api_key": KEY, "model": "deepseek-chat"}
                       ).status_code == 200
    assert KEY in keychain.data.values()
    assert client.post("/api/privacy/delete", json={"word": word(client), "delete_models": True}).status_code == 200
    assert KEY in keychain.data.values()  # deleting everything else leaves the keychain alone
    names = (home / "secret-names.json").read_text(encoding="utf-8")  # so a later deletion can still find them
    assert "provider:" in names and KEY not in names
    client.app.state.spike.secrets._keyring = keychain  # the new state would open the real keychain
    assert client.post("/api/providers", json={"preset": "deepseek", "api_key": KEY, "model": "deepseek-chat"}
                       ).status_code == 200
    res = client.post("/api/privacy/delete", json={"word": word(client), "delete_secrets": True}).json()
    assert keychain.data == {} and res["keys_removed"] >= 1 and not (home / "secret-names.json").exists()


def test_other_computers_cannot_ask_for_the_word_or_delete(tmp_path, monkeypatch):
    client = make_app(tmp_path / "home", monkeypatch)
    remote = TestClient(client.app, base_url="http://127.0.0.1", client=("192.0.2.1", 50000))
    assert remote.get("/api/privacy/delete-word").status_code == 403
    assert remote.post("/api/privacy/delete", json={"word": word(client)}).status_code == 403
    assert remote.get("/api/backup/export").status_code == 403
