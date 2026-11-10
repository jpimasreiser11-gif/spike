"""G39: sample projects bundled with SPIKE (six, Spanish and English), listed and imported through /api/samples."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from spike.finance.market import load_csv
from spike.samples import DATA, LANGS, SAMPLE_IDS, build_archive
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    return TestClient(create_app(AppState(home=tmp_path, provider_factory=factory)))


def files_of(client, pid):
    return {f["path"]: f["size"] for f in client.get(f"/api/projects/{pid}/files").json()}


def text_of(client, pid, path):
    r = client.get(f"/api/projects/{pid}/files/{path}")
    assert r.status_code == 200, r.text
    return r.content.decode("utf-8")


def test_six_samples_listed_in_both_languages(client):
    for lang in LANGS:
        rows = client.get("/api/samples", params={"lang": lang}).json()
        assert [r["id"] for r in rows] == list(SAMPLE_IDS) and len(rows) == 6
        assert all(r["name"] and r["description"] and r["files"] >= 1 for r in rows)
    assert client.get("/api/samples", params={"lang": "xx"}).json()[0]["name"]  # unknown language: English


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("sid", SAMPLE_IDS)
def test_each_sample_imports_and_its_files_load(client, sid, lang):
    r = client.post(f"/api/samples/{sid}/import", params={"lang": lang})
    assert r.status_code == 200, r.text
    project = r.json()
    files = files_of(client, project["id"])
    assert files and all(size > 0 for size in files.values())
    for path in files:
        assert text_of(client, project["id"], path).strip()
    assert project["instructions"].strip()
    assert any(p["id"] == project["id"] for p in client.get("/api/projects").json())


def test_unknown_sample_is_404(client):
    assert client.post("/api/samples/nope/import").status_code == 404


def test_samples_are_small():
    total = sum(p.stat().st_size for p in DATA.rglob("*") if p.is_file())
    assert total < 200 * 1024
    assert all(len(build_archive(s, lang)) < 60 * 1024 for s in SAMPLE_IDS for lang in LANGS)


@pytest.mark.parametrize("lang,name", [("es", "gastos.csv"), ("en", "expenses.csv")])
def test_expense_csv_parses(client, lang, name):
    pid = client.post("/api/samples/expenses/import", params={"lang": lang}).json()["id"]
    rows = list(csv.DictReader(io.StringIO(text_of(client, pid, name))))
    assert 38 <= len(rows) <= 45
    assert len({tuple(r) for r in rows}) == 1 and len(rows[0]) >= 4
    amount_col = list(rows[0])[3]
    assert all(float(r[amount_col]) > 0 for r in rows)


@pytest.mark.parametrize("lang", LANGS)
def test_handbook_is_long_enough_to_search(client, lang):
    pid = client.post("/api/samples/handbook/import", params={"lang": lang}).json()["id"]
    name = next(p for p in files_of(client, pid) if p.endswith(".md"))
    words = len(text_of(client, pid, name).split())
    assert 2700 <= words <= 4200, words


@pytest.mark.parametrize("lang", LANGS)
def test_webpage_has_html_css_js(client, lang):
    pid = client.post("/api/samples/webpage/import", params={"lang": lang}).json()["id"]
    assert {"index.html", "style.css", "app.js"} <= set(files_of(client, pid))
    html = text_of(client, pid, "index.html")
    assert "style.css" in html and "app.js" in html and "http://" not in html and "https://" not in html


@pytest.mark.parametrize("lang", LANGS)
def test_workflow_sample_validates_with_the_existing_validator(client, lang):
    pid = client.post("/api/samples/workflow/import", params={"lang": lang}).json()["id"]
    listed = client.get("/api/workflows", params={"project_id": pid}).json()
    assert len(listed) == 1
    doc = client.get(f"/api/workflows/{listed[0]['id']}", params={"project_id": pid}).json()
    r = client.post("/api/workflows/validate", params={"project_id": pid}, json={"workflow": doc})
    assert r.json() == {"ok": True, "problems": []}
    types = {n["type"] for n in doc["nodes"]}
    assert {"input", "specialist", "tool", "condition", "output"} <= types
    default = next(n["default"] for n in doc["nodes"] if n["type"] == "input" and n["kind"] == "file")
    assert default in files_of(client, pid)  # the file the flow reads is in the project


@pytest.mark.parametrize("lang", LANGS)
def test_finance_case_is_paper_only(client, lang):
    project = client.post("/api/samples/finance/import", params={"lang": lang}).json()
    pid = project["id"]
    assert project["mode"] == "finance"
    assert "paper_order" in project["instructions"]
    notes = client.get("/api/memory", params={"scope": f"project:{pid}"}).json()
    assert any(n["kind"] == "rule" for n in notes)
    # the live-order tool is only ever named in a prohibition ("never ... propose_live_order")
    texts = [project["instructions"], json.dumps(notes)]
    texts += [text_of(client, pid, p) for p in files_of(client, pid)]
    for blob in texts:
        for line in blob.lower().split("\n"):
            if "propose_live_order" in line:
                assert "nunca" in line or "never" in line, line
        assert "api_key" not in blob.lower()
    candles = load_csv(text_of(client, pid, "precios.csv" if lang == "es" else "prices.csv"))
    assert len(candles) >= 30
