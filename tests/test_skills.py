"""Skills (Agent Skills SKILL.md): loading, router selection for small local models, model choice for API models,
token budget, the API and packs."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.core.context import estimate_tokens
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.server.app import create_app
from spike.server.state import AppState
from spike.skills.engine import BUNDLED, SkillError, SkillLibrary, parse_skill
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker, ToolRegistry
from tests.helpers import ScriptedProvider, call, text

BUNDLED_NAMES = {"test-driven-development", "systematic-debugging", "writing-plans", "verification-before-completion",
                 "frontend-design", "mcp-builder", "webapp-testing", "medical-evidence-summary",
                 "financial-ratio-analysis", "campaign-brief"}


def write_skill(root: Path, name: str, description: str = "Use when testing.", body: str = "Do the thing.",
                extra: str = "") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}\n")
    return folder


def test_bundled_skills_load_with_their_licenses():
    library = SkillLibrary([(BUNDLED, "bundled")])
    skills = {s.name: s for s in library.all()}
    assert set(skills) == BUNDLED_NAMES
    for s in skills.values():
        assert s.license, s.name
        assert len(s.description) <= 1024 and s.body().strip(), s.name
    for name in ("test-driven-development", "frontend-design"):  # upstream copies carry their license file
        assert any(p.name.startswith("LICENSE") for p in skills[name].path.iterdir())
    assert skills["financial-ratio-analysis"].specialists == ["finance"]
    assert skills["systematic-debugging"].specialists == ["code", "data"]  # from bindings.yaml
    assert "systematic-debugging/root-cause-tracing.md" not in skills["systematic-debugging"].resources()
    assert "root-cause-tracing.md" in skills["systematic-debugging"].resources()


@pytest.mark.parametrize("front, error", [
    ("description: x\n", "name"),
    ("name: other\ndescription: x\n", "folder"),
    ("name: Bad_Name\ndescription: x\n", "name"),
    ("name: s\n", "description"),
])
def test_invalid_skills_are_rejected(tmp_path, front, error):
    folder = tmp_path / ("s" if "Bad" not in front else "Bad_Name")
    folder.mkdir()
    (folder / "SKILL.md").write_text(f"---\n{front}---\nbody\n")
    with pytest.raises(SkillError, match=error):
        parse_skill(folder)


@pytest.mark.parametrize("specialist, prompt, expected", [
    ("code", "Tengo un bug: el test falla con un traceback raro", "systematic-debugging"),
    ("code", "Implementa la funcionalidad de login con TDD, pruebas primero", "test-driven-development"),
    ("finance", "Calcula el margen EBITDA y el ROE de este balance", "financial-ratio-analysis"),
    ("medicine", "¿Cuál es el tratamiento de primera línea de la hipertensión según las guías?",
     "medical-evidence-summary"),
    ("marketing", "Prepara una campaña de lanzamiento con canales y KPI", "campaign-brief"),
    ("code", "Write an MCP server for my notes app", "mcp-builder"),
    ("core", "Hola, ¿qué tal estás?", None),
    ("code", "Calcula el margen EBITDA y el ROE", None),  # finance skill is not bound to Code
])
def test_router_selects_the_skill(specialist, prompt, expected):
    picked = SkillLibrary([(BUNDLED, "bundled")]).select(prompt, specialist)
    assert [s.name for s in picked] == ([expected] if expected else [])


def test_disabled_skills_are_never_selected():
    library = SkillLibrary([(BUNDLED, "bundled")])
    assert library.select("Calcula el ROE", "finance", disabled={"financial-ratio-analysis"}) == []


def test_user_skills_bind_through_metadata_and_override_bundled(tmp_path):
    write_skill(tmp_path, "campaign-brief", "Use for my own campaigns.", "My brief format.",
                "metadata:\n  spike-specialists: marketing\n  spike-keywords: campaña\n")
    library = SkillLibrary([(BUNDLED, "bundled"), (tmp_path, "user")])
    skill = library.get("campaign-brief")
    assert skill.source == "user" and skill.body().strip() == "My brief format."
    assert [s.name for s in library.select("una campaña", "marketing")] == ["campaign-brief"]


def orchestrator(provider, library, budget=24_000):
    catalog = load_catalog()
    return Orchestrator(catalog, lambda spec: Backend(provider=provider, model=None, adapter=None,
                                                       context_budget=budget),
                        ToolRegistry(), PermissionBroker(), skills=library)


async def run(orch, text_, mode, **opts):
    return [ev async for ev in orch.run([], text_, OrchestratorOptions(mode=mode, use_planner=False, **opts))]


async def test_router_mode_injects_the_skill_body_for_local_models():
    local = ScriptedProvider([text("ok")], name="spike-local")
    local.config.local = True
    events = await run(orchestrator(local, SkillLibrary([(BUNDLED, "bundled")])),
                       "Calcula el margen EBITDA y el ROE", "finance")
    system = local.requests[-1].messages[0].content
    assert "# Skill: financial-ratio-analysis" in system and "Inputs first" in system
    assert {"type": "skill", "names": ["financial-ratio-analysis"], "mode": "router",
            "specialist": "finance"} in events
    assert not local.requests[-1].tools  # no load_skill tool for small local models


async def test_a_long_skill_is_cut_to_a_quarter_of_an_8k_context():
    local = ScriptedProvider([text("ok")], name="spike-local")
    local.config.local = True
    budget = 8192 - 2048 - 512  # what AppState gives an 8K local context with max_tokens 2048
    await run(orchestrator(local, SkillLibrary([(BUNDLED, "bundled")]), budget=budget),
              "Tengo un bug, el test falla con una excepción", "code")
    system = local.requests[-1].messages[0].content
    skill_part = system[system.index("# Skill: systematic-debugging"):]
    assert estimate_tokens(skill_part) <= budget // 4 + 40 and "truncated" in skill_part
    assert sum(estimate_tokens(m.content) for m in local.requests[-1].messages) < budget


async def test_api_models_choose_skills_themselves(tmp_path):
    write_skill(tmp_path, "notes", "Use when writing meeting notes.", "Notes format body.")
    (tmp_path / "notes" / "template.md").write_text("TEMPLATE")
    remote = ScriptedProvider([call("load_skill", {"name": "notes"}),
                               call("load_skill", {"name": "notes", "file": "template.md"}),
                               call("load_skill", {"name": "notes", "file": "../../etc/passwd"}),
                               text("done")], name="remote")
    remote.config.local = False
    events = await run(orchestrator(remote, SkillLibrary([(tmp_path, "user")])), "Escribe las notas", "core")
    first = remote.requests[0]
    assert "# Available skills" in first.messages[0].content and "- notes: Use when writing meeting notes." in \
        first.messages[0].content
    assert "load_skill" in [t.name for t in first.tools]
    results = [e["content"] for e in events if e["type"] == "tool_result"]
    assert "Notes format body." in results[0] and "template.md" in results[0]
    assert results[1] == "TEMPLATE" and results[2].startswith("error")


def zip_of(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    return TestClient(create_app(state)), state, local


def test_skills_api_lists_toggles_imports_and_deletes(api, tmp_path):
    client, _, local = api
    listed = {s["name"]: s for s in client.get("/api/skills").json()}
    assert set(listed) == BUNDLED_NAMES and all(s["enabled"] for s in listed.values())
    assert client.put("/api/skills/financial-ratio-analysis", json={"enabled": False}).json()["enabled"] is False
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "Calcula el ROE", "mode": "finance"})
    assert "# Skill:" not in local.requests[-1].messages[0].content

    skill = b"---\nname: haiku\ndescription: Use when writing haiku poems.\nmetadata:\n  spike-keywords: haiku\n---\nFive seven five.\n"
    r = client.post("/api/skills/import", content=zip_of({"haiku/SKILL.md": skill, "haiku/ref.md": b"r"}))
    assert r.status_code == 200, r.text
    assert r.json()["names"] == ["haiku"]
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "write a haiku", "mode": "writing"})
    assert "Five seven five." in local.requests[-1].messages[0].content
    assert client.get("/api/skills/haiku").json()["body"].strip() == "Five seven five."
    assert client.post("/api/skills/import", content=zip_of({"../evil/SKILL.md": skill})).status_code == 400
    assert client.post("/api/skills/import", content=zip_of({"x/SKILL.md": b"no front matter"})).status_code == 400
    assert client.delete("/api/skills/test-driven-development").status_code == 400
    assert client.delete("/api/skills/haiku").json()["ok"]
    assert "haiku" not in {s["name"] for s in client.get("/api/skills").json()}


def test_pack_export_import_carries_specialists_skills_and_connectors_without_secrets(api, tmp_path):
    client, state, _ = api
    state.update_settings({"custom_specialists": [{"id": "tax", "name": "Spike Tax", "system_prompt": "You do taxes.",
                                                   "keywords": {"iva": 2}}]})
    client.post("/api/skills/import", content=zip_of({"haiku/SKILL.md": b"---\nname: haiku\ndescription: d\n---\nB\n"}))
    client.post("/api/connectors", json={"id": "mine", "name": "Mine", "command": "my-mcp", "args": ["--x"]})
    state.secrets.set("connector:mine:TOKEN", "secret-never-packed")
    pack = client.get("/api/pack/export")
    assert pack.status_code == 200 and b"secret-never-packed" not in pack.content
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(pack.content)).read("pack.json"))
    assert [s["id"] for s in manifest["specialists"]] == ["tax"] and manifest["connectors"][0]["id"] == "mine"

    other_home = tmp_path / "other"
    fresh = AppState(home=other_home, provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    other = TestClient(create_app(fresh))
    r = other.post("/api/pack/import", content=pack.content)
    assert r.status_code == 200, r.text
    assert r.json() == {"specialists": ["tax"], "skills": ["haiku"], "connectors": ["mine"]}
    assert "tax" in fresh.catalog.specialists
    assert fresh.skills.get("haiku") is not None
    mine = next(c for c in other.get("/api/connectors").json() if c["id"] == "mine")
    assert mine["enabled"] is False and mine["command"] == "my-mcp"


def test_skill_events_reach_the_web_app_and_history(api):
    client, _, local = api
    local._script = [text("ok")]
    r = client.post("/api/chat", json={"message": "Calcula el margen EBITDA", "mode": "finance"})
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert any(e["type"] == "skill" and e["names"] == ["financial-ratio-analysis"] for e in events)
    conv = client.get(f"/api/conversations/{events[0]['id']}").json()
    assert conv["messages"][-1]["meta"]["skills"] == ["financial-ratio-analysis"]
