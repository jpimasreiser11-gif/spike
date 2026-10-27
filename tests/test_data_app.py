"""A12: real workbook -> generated artifact -> reviewed edits -> approved source write, without a model."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider


@pytest.fixture
def app(tmp_path, monkeypatch):
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")
    state = AppState(home=tmp_path, provider_factory=lambda cfg: local)
    return TestClient(create_app(state)), local, tmp_path

def create(client, path="stock.xlsx", **extra):
    return client.post("/api/creator/data-app", json={"file": path, "lang": "es", "approved": True, **extra})


def test_xlsx_to_app_edit_approved_write(app):
    openpyxl = pytest.importorskip("openpyxl")
    client, _, home = app
    source = home / "ws" / "stock.xlsx"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes((Path(__file__).parent / "fixtures" / "stock.xlsx").read_bytes())
    original = source.read_bytes()
    assert create(client, approved=False).status_code == 403
    made = create(client)
    assert made.status_code == 200, made.text
    doc = made.json()
    assert (home / "ws" / doc["path"]).read_text(encoding="utf-8") == doc["html"]
    assert "postMessage" in doc["html"] and "fetch(" not in doc["html"]
    proposal = client.post(f"/api/creator/data-app/{doc['id']}/preview", json={"edits": [{"row": 0, "column": 1, "value": "12"}]}).json()
    assert proposal["changes"] == [{"row": 0, "column": 1, "before": "5", "after": "12"}]
    assert source.read_bytes() == original
    url = f"/api/creator/data-app/{doc['id']}/approve"
    assert client.post(url, json={"token": proposal["token"]}).status_code == 403
    assert client.post(url, json={"token": proposal["token"], "approved": True}).status_code == 200
    book = openpyxl.load_workbook(source)
    assert book.active["B2"].value == 12 and book["Notes"]["A1"].value == "Preserve me"
    book.close()
    assert client.post(url, json={"token": proposal["token"], "approved": True}).status_code == 409


def test_csv_conflicts_and_boundaries(app, tmp_path):
    client, _, home = app
    root = home / "ws"
    root.mkdir(exist_ok=True)
    source = root / "stock.csv"
    source.write_text('nombre,cantidad\nCafé,5\n', encoding="utf-8")
    doc = create(client, "stock.csv").json()
    base = f"/api/creator/data-app/{doc['id']}"
    for edits in ([{"row": -1, "column": 0, "value": "x"}], [{"row": 0, "column": 2, "value": "x"}],
                  [{"row": 0, "column": 0, "value": "=HYPERLINK(1)"}]):
        assert client.post(base + "/preview", json={"edits": edits}).status_code == 400
    proposal = client.post(base + "/preview", json={"edits": [{"row": 0, "column": 0, "value": "Té"}]}).json()
    source.write_text("changed", encoding="utf-8")
    assert client.post(base + "/approve", json={"token": proposal["token"], "approved": True}).status_code == 409
    assert source.read_text(encoding="utf-8") == "changed"
    assert create(client, "../outside.csv").status_code == 400
    assert create(client, "bad.json").status_code == 400
    if hasattr(Path, "symlink_to"):
        link = root / "link.csv"
        try:
            link.symlink_to(source)
        except OSError:
            return
        assert create(client, "link.csv").status_code == 400


def test_csv_approved_roundtrip_and_escaping(app):
    client, _, home = app
    root = home / "ws"
    root.mkdir(exist_ok=True)
    source = root / "stock.csv"
    source.write_text('nombre,cantidad\n</script><img src=x>,5\n', encoding="utf-8")
    doc = create(client, "stock.csv", lang="en").json()
    assert "</script><img" not in doc["html"]
    base = f"/api/creator/data-app/{doc['id']}"
    proposal = client.post(base + "/preview", json={"edits": [{"row": 0, "column": 0, "value": "Café, té"}]}).json()
    assert client.post(base + "/approve", json={"token": proposal["token"], "approved": True}).status_code == 200
    assert '"Café, té",5' in source.read_text(encoding="utf-8")


def test_project_scope_and_invalid_workbooks(app):
    client, _, home = app
    project = client.post('/api/projects', json={'name': 'Stock'}).json()
    client.put(f"/api/projects/{project['id']}/files/stock.csv", content=b'name,qty\ncoffee,5\n')
    made = create(client, 'stock.csv', project_id=project['id'])
    assert made.status_code == 200, made.text
    doc = made.json()
    assert client.get(f"/api/projects/{project['id']}/files/{doc['path']}").status_code == 200
    assert create(client, 'stock.csv', project_id='missing').status_code == 404
    source = home / 'ws' / 'bad.xlsx'
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(b'not a workbook')
    assert create(client, 'bad.xlsx').status_code == 400


def test_formula_cells_and_invalid_numeric_edits_never_modify_xlsx(app):
    openpyxl = pytest.importorskip('openpyxl')
    client, _, home = app
    root = home / 'ws'
    root.mkdir(exist_ok=True)
    source = root / 'formula.xlsx'
    book = openpyxl.Workbook()
    book.active.append(['Value', 'Formula'])
    book.active.append([5, '=A2*2'])
    book.save(source)
    book.close()
    original = source.read_bytes()
    doc = create(client, 'formula.xlsx').json()
    base = f"/api/creator/data-app/{doc['id']}"
    for column, value in ((1, '10'), (0, 'not a number')):
        proposal = client.post(base + '/preview', json={'edits': [{'row': 0, 'column': column, 'value': value}]}).json()
        assert client.post(base + '/approve', json={'token': proposal['token'], 'approved': True}).status_code == 400
        assert source.read_bytes() == original


def test_limit_missing_extra_and_expiry(app, monkeypatch):
    import builtins

    from spike import data_app
    from spike.server import data_app_api

    client, _, home = app
    root = home / 'ws'
    root.mkdir(exist_ok=True)
    source = root / 'stock.csv'
    source.write_text('name,qty\ncoffee,5\n', encoding='utf-8')
    doc = create(client, 'stock.csv').json()
    base = f"/api/creator/data-app/{doc['id']}"
    edit = {'edits': [{'row': 0, 'column': 0, 'value': 'tea'}]}
    first = client.post(base + '/preview', json=edit).json()
    second = client.post(base + '/preview', json=edit).json()
    assert first['token'] != second['token']
    assert client.post(base + '/approve', json={'token': first['token'], 'approved': True}).status_code == 409
    original_time = data_app_api.time.monotonic
    monkeypatch.setattr(data_app_api.time, 'monotonic', lambda: original_time() + 3601)
    assert client.post(base + '/preview', json=edit).status_code == 409
    monkeypatch.undo()
    source.write_bytes(b'x' * (data_app.MAX_BYTES + 1))
    assert create(client, 'stock.csv').status_code == 400
    (root / 'stock.xlsx').write_bytes((Path(__file__).parent / 'fixtures' / 'stock.xlsx').read_bytes())
    original_import = builtins.__import__

    def without_xlsx(name, *args, **kwargs):
        if name == 'openpyxl':
            raise ImportError('optional extra unavailable')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', without_xlsx)
    assert create(client, 'stock.xlsx').status_code == 400


def test_xlsx_integer_edits_keep_precision(app):
    openpyxl = pytest.importorskip('openpyxl')
    client, _, home = app
    source = home / 'ws' / 'integer.xlsx'
    source.parent.mkdir(exist_ok=True)
    book = openpyxl.Workbook()
    book.active.append(['Integer'])
    book.active.append([5])
    book.save(source)
    book.close()
    doc = create(client, 'integer.xlsx').json()
    base = f"/api/creator/data-app/{doc['id']}"
    proposal = client.post(base + '/preview', json={'edits': [{'row': 0, 'column': 0, 'value': '9007199254740993'}]}).json()
    # Values outside Excel's reliable 15-digit numeric precision must be rejected, rather than silently rounded.
    assert client.post(base + '/approve', json={'token': proposal['token'], 'approved': True}).status_code == 400
    book = openpyxl.load_workbook(source)
    assert book.active['A2'].value == 5
    book.close()


def test_negative_numbers_are_editable_but_formula_prefixes_are_not(app):
    client, _, home = app
    root = home / 'ws'
    root.mkdir(exist_ok=True)
    (root / 'stock.csv').write_text('name,qty\ncoffee,5\n', encoding='utf-8')
    doc = create(client, 'stock.csv').json()
    base = f"/api/creator/data-app/{doc['id']}"
    proposal = client.post(base + '/preview', json={'edits': [{'row': 0, 'column': 1, 'value': '-12.5'}]})
    assert proposal.status_code == 200
    assert client.post(base + '/preview', json={'edits': [{'row': 0, 'column': 1, 'value': '-SUM(A1)'}]}).status_code == 400


def test_xlsx_generated_app_end_to_end(app):
    """Execute the generated app's actual search/edit JavaScript offline, then approve its emitted proposal."""
    import json
    import shutil
    import subprocess

    openpyxl = pytest.importorskip('openpyxl')
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    if not node or not (root / 'web' / 'node_modules' / 'jsdom').is_dir():
        pytest.skip('offline generated-app execution needs the existing web dev environment (Node and jsdom)')
    client, _, home = app
    source = home / 'ws' / 'stock.xlsx'
    source.parent.mkdir(exist_ok=True)
    original = (Path(__file__).parent / 'fixtures' / 'stock.xlsx').read_bytes()
    source.write_bytes(original)
    doc = create(client).json()
    result = subprocess.run([node, str(root / 'web' / 'e2e' / 'data-app-dom.mjs')], input=doc['html'],
                            capture_output=True, encoding='utf-8', timeout=10, check=True)
    proposal = json.loads(result.stdout)
    base = f"/api/creator/data-app/{doc['id']}"
    reviewed = client.post(base + '/preview', json={'edits': proposal['edits']}).json()
    assert source.read_bytes() == original
    assert client.post(base + '/approve', json={'token': reviewed['token'], 'approved': True}).status_code == 200
    book = openpyxl.load_workbook(source)
    assert book.active['B2'].value == 12
    book.close()
