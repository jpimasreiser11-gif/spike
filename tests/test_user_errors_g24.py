"""G24 — User-facing error messages & API error hygiene.

Verifies that:
1. Sweeping API routes with invalid inputs (bad types, missing IDs, path traversals, bad Content-Length,
   missing model/adapter files, overlapping folders, nested git repos) never responds 500 and never leaks
   internal tracebacks or host absolute filesystem paths.
2. User-facing error codes and messages returned by the server have bilingual (es/en) translations in
   `web/src/i18n.ts` (`projectErrors` / `projectError`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState

REPO_ROOT = Path(__file__).resolve().parents[1]
I18N_TS = REPO_ROOT / "web" / "src" / "i18n.ts"

ABS_PATH_RE = re.compile(
    r"(/Users/[^\s\"']+|/private/[^\s\"']+|/var/folders/[^\s\"']+|/tmp/[^\s\"']+|[A-Za-z]:\\[^\s\"']+|Traceback \(most recent)"
)


def _assert_clean_error(res, tmp_root: str, label: str) -> None:
    assert res.status_code < 500, f"{label} returned {res.status_code}: {res.text[:300]}"
    body = res.text
    assert tmp_root not in body, f"{label} leaked tmp_path in response: {body[:300]}"
    match = ABS_PATH_RE.search(body)
    assert match is None, f"{label} leaked path/traceback ({match.group(0)!r}): {body[:300]}"


def test_api_routes_reject_invalid_inputs_without_500_or_leaking_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "spike-home"
    ws = tmp_path / "workspace"
    home.mkdir()
    ws.mkdir()
    monkeypatch.setenv("SPIKE_HOME", str(home))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(ws))

    state = AppState(home=home)
    app = create_app(state)
    client = TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    tmp_str = str(tmp_path)

    # Create a project to exercise project-scoped endpoints
    proj = client.post("/api/projects", json={"name": "Demo"}).json()
    pid = proj["id"]

    # 1. Malformed Content-Length headers on raw upload endpoints must return 400, never 500
    upload_urls = [
        "/api/design-systems/import",
        "/api/skills/import",
        "/api/pack/import",
        "/api/projects/import",
        "/api/memory-import",
        "/api/glossary-import",
        "/api/analytics/report",
        f"/api/projects/{pid}/files/notes.txt",
    ]
    for url in upload_urls:
        method = "PUT" if "/files/" in url else "POST"
        res = client.request(method, url, content=b"x", headers={"content-length": "not-a-number"})
        _assert_clean_error(res, tmp_str, f"{method} {url} (bad Content-Length)")
        assert res.status_code == 400

    # 2. Malformed settings payloads in PUT /api/settings must return 400, never 500 or corrupt state
    bad_settings = [
        {"custom_specialists": "not-a-list"},
        {"custom_specialists": [123]},
        {"custom_specialists": [{"id": "incomplete"}]},
        {"tool_policies": "not-a-dict"},
        {"specialist_bindings": "not-a-dict"},
        {"specialist_instructions": "not-a-dict"},
        {"disabled_skills": "not-a-list"},
        {"memory": "not-a-dict"},
        {"evolution": "not-a-dict"},
        {"local_runtime": "not-a-dict"},
        {"finance": "not-a-dict"},
        {"trust": "not-a-dict"},
        {"desktop": "not-a-dict"},
        {"sandbox": "invalid_mode"},
        {"unknown_key": True},
    ]
    for payload in bad_settings:
        res = client.put("/api/settings", json=payload)
        _assert_clean_error(res, tmp_str, f"PUT /api/settings {payload}")
        assert res.status_code == 400

    # 3. Runtime start with missing model file must not leak host absolute path
    missing_model = tmp_path / "secret_dir" / "missing-model.gguf"
    client.put(
        "/api/settings",
        json={
            "local_runtime": {
                "model": str(missing_model),
                "adapters": [],
                "context": None,
                "threads": None,
                "gpu_layers": None,
                "kv_cache_type": "q8_0",
                "port": 8737,
            }
        },
    )
    res = client.post("/api/runtime/start")
    _assert_clean_error(res, tmp_str, "POST /api/runtime/start (missing model)")
    assert res.status_code == 400

    # 4. Evolution adapter rollback when previous history file was deleted must not leak host path
    gone_file = home / "adapters" / "history" / "medicine-gone.gguf"
    state.evolution.store.add_version(
        "adapter:medicine",
        {"file": str(gone_file), "sha256": "a" * 64, "source": str(gone_file)},
        {"accepted": True},
        "v1",
    )
    state.evolution.store.add_version(
        "adapter:medicine",
        {"file": str(gone_file), "sha256": "b" * 64, "source": str(gone_file)},
        {"accepted": True},
        "v2",
    )
    res = client.post("/api/evolution/rollback", json={"component": "adapter:medicine"})
    _assert_clean_error(res, tmp_str, "POST /api/evolution/rollback (missing previous adapter file)")
    assert res.status_code == 409

    # 5. Memory folders overlap error must not leak full absolute path of existing indexed folder
    docs_dir = tmp_path / "my_notes"
    sub_dir = docs_dir / "nested"
    sub_dir.mkdir(parents=True)
    res1 = client.post("/api/memory-folders", json={"path": str(docs_dir)})
    assert res1.status_code == 200
    res2 = client.post("/api/memory-folders", json={"path": str(sub_dir)})
    _assert_clean_error(res2, tmp_str, "POST /api/memory-folders (overlap)")
    assert res2.status_code == 400

    # 6. Sweep across API routes with invalid inputs and path traversal attempts
    secret_abs = f"{tmp_str}/secret.txt"
    cases = [
        ("GET", "/api/design-systems/nonexistent", None),
        ("GET", "/api/design-systems/nonexistent/preview", None),
        ("POST", "/api/design-systems/import", b"not a zip"),
        ("DELETE", "/api/design-systems/nonexistent", None),
        ("GET", "/api/skills/nonexistent", None),
        ("PUT", "/api/skills/nonexistent", {"enabled": False}),
        ("POST", "/api/skills/import", b"not a zip"),
        ("DELETE", "/api/skills/nonexistent", None),
        ("POST", "/api/pack/import", b"not a zip"),
        ("GET", "/api/connectors/nonexistent/view?uri=ui://x", None),
        ("POST", "/api/connectors", {"id": "bad id!", "name": "x", "transport": "stdio", "command": "echo"}),
        ("PUT", "/api/connectors/nonexistent", {"enabled": True}),
        ("DELETE", "/api/connectors/nonexistent", None),
        ("PUT", "/api/browser/domains/not_a_domain!", {"rule": "allow"}),
        ("POST", "/api/providers", {"id": "p1", "name": "P1", "kind": "openai", "base_url": "ftp://bad"}),
        ("PATCH", "/api/providers/nonexistent", {"base_url": "https://example.com"}),
        ("DELETE", "/api/providers/spike-local", None),
        ("POST", "/api/providers/nonexistent/test", {}),
        ("POST", "/api/finance/paper/orders/nonexistent/cancel", {}),
        ("POST", "/api/finance/live/check", {}),
        ("GET", "/api/finance/live/orders/nonexistent", None),
        ("POST", "/api/finance/live/orders/nonexistent/confirm", {"id": "nonexistent"}),
        ("POST", "/api/finance/live/orders/nonexistent/cancel", {}),
        ("POST", "/api/analytics/report", {"format": "pdf", "title": "x", "blocks": [{"kind": "image", "png": "!!!"}]}),
        ("POST", "/api/projects/import", b"not a zip"),
        ("GET", "/api/projects/nonexistent", None),
        ("PATCH", f"/api/projects/{pid}", {"mode": "nonexistent_mode"}),
        ("PATCH", f"/api/projects/{pid}", {"design": "nonexistent_ds"}),
        ("PUT", f"/api/projects/{pid}/files/..%2Foutside.txt", b"hi"),
        ("PUT", f"/api/projects/{pid}/files/{secret_abs}", b"hi"),
        ("GET", f"/api/projects/{pid}/files/nonexistent.txt", None),
        ("GET", "/api/workspace/files/..%2Foutside.txt", None),
        ("GET", f"/api/workspace/files/{secret_abs}", None),
        ("DELETE", f"/api/projects/{pid}/files/nonexistent.txt", None),
        ("GET", "/api/projects/nonexistent/compare", None),
        ("GET", "/api/conversations/nonexistent", None),
        ("PATCH", "/api/conversations/nonexistent", {"title": "x"}),
        ("GET", "/api/conversations/nonexistent/proof", None),
        ("POST", "/api/conversations/nonexistent/branch", {"before": "m1"}),
        ("POST", "/api/checkpoints/nonexistent/undo", {"force": False}),
        ("POST", "/api/messages/nonexistent/learn", {"action": "dismiss"}),
        ("POST", "/api/messages/nonexistent/escalate", {"provider_id": "nonexistent"}),
        ("POST", "/api/messages/nonexistent/route", {"specialist": "nonexistent"}),
        ("DELETE", "/api/evolution/items/nonexistent", None),
        ("GET", "/api/evolution/items/nonexistent/issue", None),
        ("POST", "/api/evolution/prompts/nonexistent/optimize", {}),
        ("POST", "/api/evolution/prompts/nonexistent/candidate", {"instructions": ["x"]}),
        ("POST", "/api/evolution/prompts/nonexistent/activate", {}),
        ("GET", "/api/evolution/nonexistent.jsonl", None),
        ("POST", "/api/evolution/rollback", {"component": "unknown"}),
        ("POST", "/api/evolution/personal/marks", {"conversation": "nonexistent"}),
        ("DELETE", "/api/evolution/personal/marks/nonexistent", None),
        ("PUT", "/api/evolution/personal/exclusions", {"ref": "nonexistent", "excluded": True}),
        ("GET", "/api/memory?scope=invalid_scope", None),
        ("PUT", "/api/memory/nonexistent", {"text": "x"}),
        ("DELETE", "/api/memory/nonexistent", None),
        ("POST", "/api/memory-import", b"not json"),
        ("POST", "/api/memory-folders", {"path": f"{tmp_str}/does_not_exist"}),
        ("GET", "/api/memory-folders/nonexistent", None),
        ("DELETE", "/api/memory-folders/nonexistent", None),
        ("PUT", "/api/glossary/nonexistent", {"term": "a", "translation": "b"}),
        ("DELETE", "/api/glossary/nonexistent", None),
        ("PATCH", "/api/tutor/nonexistent", {"name": "x"}),
        ("POST", "/api/tutor/nonexistent/review", {"grade": 3}),
        ("DELETE", "/api/tutor/nonexistent", None),
        ("PATCH", "/api/memory-graph/relations/nonexistent", {"status": "confirmed"}),
        ("DELETE", "/api/memory-graph/relations/nonexistent", None),
        ("POST", "/api/memory-graph/propose", {"memory_id": "nonexistent"}),
        ("POST", "/api/desktop/estimate", {}),
        ("POST", "/api/desktop/actions/nonexistent", {"decision": "deny"}),
        ("GET", "/api/desktop/shots/nonexistent/0", None),
        ("PUT", "/api/media/settings", {"enabled": True, "whisper_model": secret_abs}),
        ("POST", "/api/media/transcribe", {"audio": "not_base64!!!"}),
        ("POST", "/api/media/speak", {"text": "hola"}),
        ("POST", "/api/reverse/preview", {"source": "url", "url": "https://example.com", "authorized": False}),
        ("POST", "/api/reverse/generate", {"preview_id": "nonexistent", "authorized": True}),
        ("PUT", "/api/reverse/file", {"path": secret_abs, "html": "<html></html>"}),
        ("POST", "/api/subtitles/import", {"text": "bad", "format": "srt"}),
        ("POST", "/api/subtitles/transcribe", {"path": secret_abs, "approved": True}),
        ("POST", "/api/browser/recorder/start", {}),
        ("GET", "/api/browser/scripts/nonexistent", None),
        ("DELETE", "/api/browser/scripts/nonexistent", None),
        ("POST", "/api/browser/replay", {"script": "nonexistent"}),
        ("POST", "/api/browser/replay/answer", {"question": "q", "decision": "cancel"}),
        ("POST", "/api/device-lab/run", {"url": "http://example.com", "profiles": ["mobile"], "approved": True}),
        ("POST", "/api/device-lab/android", {"serial": "bad serial!", "url": "http://localhost:8000", "approved": True}),
        ("POST", "/api/permissions/nonexistent", {"decision": "deny"}),
        ("POST", "/api/questions/nonexistent", {"answer": "x"}),
        ("POST", "/api/creator/blueprint", {"template": "nonexistent", "fields": {}}),
        ("POST", "/api/creator/data-app", {"project_id": "nonexistent", "file": "missing.csv", "title": "x"}),
        ("POST", "/api/creator/data-app/nonexistent/preview", {"edits": [{"row": 0, "column": 0, "value": "1"}]}),
        ("POST", "/api/creator/data-app/nonexistent/approve", {"token": "x" * 32, "approved": True}),
        ("POST", "/api/research/preview", {"kind": "paper", "paths": [secret_abs], "project_id": pid}),
        ("POST", "/api/research/analyze", {"preview_id": "nonexistent"}),
        ("GET", "/api/research/notebooks/nonexistent", None),
        ("POST", "/api/history/search", {"query": "hi", "scope": "project", "project_id": "nonexistent"}),
        ("POST", "/api/setup/download", {"specialists": ["code"]}),
        ("GET", "/api/workflows/nonexistent", None),
        ("DELETE", "/api/workflows/nonexistent", None),
        ("POST", "/api/workflows/nonexistent/runs", {"inputs": {}}),
        ("POST", "/api/workflows/nonexistent/runs/nonexistent/stop", {}),
        ("POST", "/api/lab/preview", {"kind": "compare", "prompt": "hi", "cases": [], "targets": [{"specialist": "bad", "provider_id": None}]}),
        ("POST", "/api/lab/execute", {"quote_id": "nonexistent"}),
        ("GET", "/api/lab/runs/nonexistent/export", None),
        ("POST", "/api/forge/blueprint", {"task": "hi", "provider_id": "nonexistent"}),
        ("GET", "/api/forge/prototypes/nonexistent", None),
        ("POST", "/api/forge/prototypes/nonexistent/merge", {"choice": "a", "approve": True}),
        ("POST", "/api/forge/prototypes/nonexistent/discard", {}),
        ("POST", "/api/minds/estimate", {"message": "hi", "n": 2, "mode": "nonexistent"}),
        ("POST", "/api/chat", {"message": "hi", "mode": "nonexistent"}),
        ("POST", "/api/specialist-documents", {"specialist": "nonexistent", "filename": "a.md", "text": "x"}),
        ("POST", "/api/jobs/nonexistent/cancel", {}),
    ]

    for method, url, body in cases:
        if isinstance(body, bytes):
            res = client.request(method, url, content=body, headers={"Content-Type": "application/octet-stream"})
        elif body is None:
            res = client.request(method, url)
        else:
            res = client.request(method, url, json=body)
        _assert_clean_error(res, tmp_str, f"{method} {url}")
        assert 400 <= res.status_code < 500, f"{method} {url} expected 4xx, got {res.status_code}"


def test_i18n_project_errors_cover_server_error_messages() -> None:
    text = I18N_TS.read_text(encoding="utf-8")
    required_keys = [
        "design system not found",
        "skill not found",
        "built-in skills can be disabled, not deleted",
        "connector not found",
        "provider not found",
        "the built-in local provider cannot be removed",
        "project not found",
        "file not found",
        "invalid file path",
        "conversation not found",
        "memory not found",
        "folder not found",
        "entry not found",
        "topic not found",
        "relation not found",
        "no pending permission request with this id",
        "no pending question with this id",
        "data_app_expired",
        "data_app_conflict",
        "data_app_approval",
        "data_app_project",
        "data_app_invalid",
        "history_filter",
        "project_not_found",
        "invalid_target",
        "invalid_cases",
        "one_probe_target",
        "expired_quote",
        "changed_quote",
        "provider_blocked",
        "unknown_run",
        "Launcher only",
        "Adapter unavailable",
        "Installation busy or insufficient resources",
    ]
    missing = [k for k in required_keys if f'"{k}"' not in text and f"'{k}'" not in text]
    assert not missing, f"Missing keys in web/src/i18n.ts projectErrors: {missing}"
