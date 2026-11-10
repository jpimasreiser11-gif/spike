"""G33 — the first-use tour keeps its "seen" flag in the server's settings store."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    return TestClient(create_app(AppState(home=tmp_path), allowed_hosts={"testserver", "127.0.0.1"}))


def test_tour_is_unseen_by_default_and_the_flag_persists(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/settings").json()["onboarding"] == {"tour_seen": False}
    assert client.put("/api/settings", json={"onboarding": {"tour_seen": True}}).json()["onboarding"] == {"tour_seen": True}
    # a new app over the same home (a restart) still reads it
    again = TestClient(create_app(AppState(home=tmp_path), allowed_hosts={"testserver", "127.0.0.1"}))
    assert again.get("/api/settings").json()["onboarding"]["tour_seen"] is True
    assert client.put("/api/settings", json={"onboarding": {"tour_seen": False}}).json()["onboarding"]["tour_seen"] is False


def test_onboarding_setting_is_validated(client: TestClient) -> None:
    assert client.put("/api/settings", json={"onboarding": "yes"}).status_code == 400
    assert client.put("/api/settings", json={"onboarding": {"tour_seen": "yes"}}).status_code == 400
    assert client.put("/api/settings", json={"onboarding": {"other": 1}}).status_code == 400
