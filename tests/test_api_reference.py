"""G37: docs/api is generated from the app's OpenAPI (plus /mcp, which is outside the schema) and kept current."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "api_reference.py"
sys.path.insert(0, str(ROOT / "scripts"))


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")


def test_the_script_writes_both_languages(tmp_path):
    result = run("--out", str(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    for lang in ("en", "es"):
        index = (tmp_path / lang / "README.md").read_text(encoding="utf-8")
        for page in ("v1.md", "mcp.md", "projects.md", "settings.md"):
            assert (tmp_path / lang / page).is_file(), f"{lang}/{page} missing"
            assert f"({page})" in index, f"{lang}/README.md does not link {page}"
    assert (tmp_path / "README.md").is_file()


def test_the_committed_reference_is_current():
    result = run("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fails_after_a_change(tmp_path):
    copy = tmp_path / "api"
    shutil.copytree(ROOT / "docs" / "api", copy)
    page = copy / "en" / "projects.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")
    result = run("--check", "--out", str(copy))
    assert result.returncode == 1
    assert "en/projects.md" in result.stdout
    (copy / "es" / "projects.md").unlink()
    assert "es/projects.md" in run("--check", "--out", str(copy)).stdout


def test_a_new_route_changes_the_reference(tmp_path):
    import api_reference
    from fastapi import HTTPException

    app = api_reference.build_app(tmp_path)
    before = api_reference.render(app)

    @app.post("/api/projects/{pid}/frobnicate")
    async def frobnicate(pid: str, level: int) -> dict:
        """Frobnicate a project."""
        raise HTTPException(409, "already frobnicated")

    app.openapi_schema = None
    after = api_reference.render(app)
    assert after != before
    page = after["en/projects.md"]
    assert "### `POST /api/projects/{pid}/frobnicate`" in page
    assert "| `409` | already frobnicated |" in page
    assert "curl -s -X POST 'http://127.0.0.1:8740/api/projects/<pid>/frobnicate?level=<level>'" in page


def test_content_covers_parameters_bodies_curl_and_errors():
    en = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "api" / "en").glob("*.md")}
    es = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "api" / "es").glob("*.md")}
    assert en.keys() == es.keys()
    everything = "\n".join(en.values())
    for code in ("400", "403", "404", "409", "413", "422"):
        assert f"| `{code}` |" in everything, f"no route documents {code}"
    assert "### `POST /v1/chat/completions`" in en["v1.md"] and "| `messages` |" in en["v1.md"]
    assert "| `401` |" in en["v1.md"]
    assert "### `POST /mcp`" in en["mcp.md"] and "tools/call" in en["mcp.md"]
    assert "http://127.0.0.1:8740" in en["README.md"] and "8741" not in everything
    assert "curl -s" in en["projects.md"] and "| Field | Type | Required |" in everything
    assert "| Campo | Tipo | Obligatorio |" in "\n".join(es.values())
    routes = sum(text.count("\n### `") for name, text in en.items() if name != "README.md")
    assert routes == sum(text.count("\n### `") for name, text in es.items() if name != "README.md")
    assert routes > 150


def test_output_is_deterministic(tmp_path):
    import api_reference

    first = api_reference.render(api_reference.build_app(tmp_path / "a"))
    second = api_reference.render(api_reference.build_app(tmp_path / "b"))
    assert first == second
