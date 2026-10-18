"""Creator (C8): templates become Forge blueprints that pass Forge's own strict check, answers are validated, and the
run follows the template's skills (only in the steps that produce something) and design system."""

import json

import pytest
from fastapi.testclient import TestClient

from spike import creator
from spike.forge.blueprint import from_user
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from tests.helpers import ScriptedProvider, call, text

CATALOG = load_catalog()
ANSWERS = {"web": {"about": "la panadería de mi barrio", "sections": "horarios, productos"},
           "app": {"about": "llevar la lista de la compra"},
           "dashboard": {"file": "ventas.csv", "focus": "ventas por mes"},
           "data_app": {"file": "datos/stock.xlsx", "about": "ver qué productos reponer"},
           "document": {"about": "digitalizar las reservas", "audience": "la dirección", "pages": "4"},
           "presentation": {"about": "resultados del trimestre", "slides": "6"},
           "video": {"about": "presentar mi app de recetas", "seconds": "8", "size": "9:16"},
           "automation": {"about": "renombrar fotos con su fecha"}}


def test_the_screen_lists_the_templates_in_both_languages():
    es, en = creator.templates("es"), creator.templates("en")
    assert [t["id"] for t in es] == ["web", "app", "dashboard", "data_app", "document", "presentation", "video",
                                     "automation"]
    assert es[0]["name"] == "Página web" and en[0]["name"] == "Web page"
    assert es[2]["fields"][0] == {"id": "file", "label": "Archivo de datos", "kind": "file", "required": True,
                                  "placeholder": "ventas.csv (en la carpeta del proyecto o del espacio de trabajo)",
                                  "default": ""}
    assert creator.templates("fr") == en
    for t in es:
        for skill in t["skills"]:
            assert skill in {"frontend-design", "verification-before-completion", "motion-scene"}
    video = next(t for t in es if t["id"] == "video")
    assert video["fields"][2]["kind"] == "choice" and video["fields"][2]["options"] == ["16:9", "9:16", "1:1"]
    assert "options" not in es[0]["fields"][0]


@pytest.mark.parametrize("template", list(ANSWERS))
@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_template_is_a_blueprint_forge_accepts(template, lang):
    built = creator.build(template, ANSWERS[template], lang)
    bp = from_user(built["blueprint"], CATALOG)  # the same strict check as a blueprint the user edited
    assert bp.steps and bp.criteria and bp.deliverables
    for step in bp.steps:
        assert "{" not in step.instruction and "}" not in step.instruction  # every placeholder filled
        tools = CATALOG.specialists[step.specialist].tools
        for path in step.deliverables:  # the step's specialist has the tool that writes its file
            assert {".docx": "create_docx", ".pptx": "create_pptx", ".mp4": "render_video"}.get(
                path[path.rfind("."):], "write_file") in tools
        if "data_sql" in step.instruction:
            assert {"data_describe", "data_sql"} <= set(tools)
    assert built["task"] == built["blueprint"]["goal"] and built["blueprint"]["method"] == "template"


def test_answers_fill_the_steps_and_the_criteria():
    web = creator.build("web", ANSWERS["web"])
    step = web["blueprint"]["steps"][0]
    assert step["specialist"] == "code" and step["deliverables"] == ["index.html"]
    assert "la panadería de mi barrio" in step["instruction"] and "Secciones: horarios, productos." in step["instruction"]
    assert web["skills"] == ["frontend-design"] and web["design"] is True
    plain = creator.build("web", {"about": "x"})["blueprint"]["steps"][0]["instruction"]
    assert "Secciones" not in plain  # an optional answer left empty adds nothing
    deck = creator.build("presentation", ANSWERS["presentation"])
    assert "6 diapositivas" in deck["blueprint"]["steps"][0]["instruction"]
    assert deck["blueprint"]["criteria"][0].startswith("presentacion.pptx tiene unas 6 diapositivas")
    dash = creator.build("dashboard", ANSWERS["dashboard"])["blueprint"]
    assert [(s["specialist"], s["role"], s["depends_on"]) for s in dash["steps"]] == [
        ("data", "research", []), ("code", "execute", ["t1"])]
    assert "data_sql" in dash["steps"][0]["instruction"] and "ventas.csv" in dash["steps"][0]["instruction"]
    doc = creator.build("document", {"about": "x"})["blueprint"]["steps"][0]["instruction"]
    assert "Unas 3 páginas" in doc  # the default
    clip = creator.build("video", ANSWERS["video"])
    assert clip["skills"] == ["motion-scene"] and clip["blueprint"]["steps"][0]["deliverables"] == ["escena.html", "video.mp4"]
    assert 'content="8"' in clip["blueprint"]["steps"][0]["instruction"] and "size 9:16" in clip["blueprint"]["steps"][0]["instruction"]


@pytest.mark.parametrize("template, answers, message", [
    ("web", {}, "required"), ("nope", {}, "unknown template"),
    ("document", {"about": "x", "pages": "muchas"}, "whole number"), ("presentation", {"about": "x", "slides": "99"},
                                                                      "whole number"),
    ("dashboard", {"file": "../secreto.csv"}, "not a relative file path"),
    ("dashboard", {"file": "notas.docx"}, "not a data file"), ("video", {"about": "x", "size": "4:3"}, "one of")])
def test_bad_answers_are_refused(template, answers, message):
    with pytest.raises(ValueError, match=message):
        creator.build(template, answers)


def test_answers_cannot_inject_format_fields():
    step = creator.build("web", {"about": "{single} {about.__class__}"})["blueprint"]["steps"][0]["instruction"]
    assert "(single) (about.__class__)" in step


@pytest.fixture
def app(tmp_path, monkeypatch):
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    state.broker.policies["write_file"] = "allow"
    client = TestClient(create_app(state))
    client.get("/api/providers")
    return client, local, tmp_path


def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_the_api_builds_a_template_and_forge_runs_it_with_its_skill_and_design(app):
    client, local, home = app
    assert [t["id"] for t in client.get("/api/creator/templates", params={"lang": "en"}).json()][0] == "web"
    bad = client.post("/api/creator/blueprint", json={"template": "dashboard", "fields": {"file": "/etc/passwd"}})
    assert bad.status_code == 400 and "relative" in bad.json()["detail"]
    (home / "ws" / "datos" / ".oculto").mkdir(parents=True)
    for name in ("ventas.csv", "datos/stock.xlsx", "datos/.oculto/x.csv", "notas.md"):
        (home / "ws" / name).write_text("a\n1\n")
    assert client.get("/api/creator/data-files").json() == [{"path": "datos/stock.xlsx", "bytes": 4},
                                                           {"path": "ventas.csv", "bytes": 4}]
    project = client.post("/api/projects", json={"name": "P"}).json()
    client.put(f"/api/projects/{project['id']}/files/q.parquet", content=b"PAR1")
    assert [f["path"] for f in client.get("/api/creator/data-files", params={"project_id": project["id"]}).json()] == [
        "q.parquet"]
    assert client.get("/api/creator/data-files", params={"project_id": "nope"}).status_code == 404
    built = client.post("/api/creator/blueprint", json={"template": "dashboard", "fields": ANSWERS["dashboard"]}).json()
    systems: dict[str, str] = {}

    def script(request):
        system, last = request.messages[0].content, request.messages[-1]
        if request.json_schema and "results" in json.dumps(request.json_schema):
            return text(json.dumps({"results": [], "criteria": [{"n": 1, "ok": True}, {"n": 2, "ok": True}]}))
        if "You are Spike Data" in system:
            systems["data"] = system
            return text("Total: 160 (SELECT sum(unidades * precio) FROM ventas)")
        if "You are Spike Code" in system:
            systems["code"] = system
            if last.role == "tool":
                return text("Guardé dashboard.html")
            return call("write_file", {"path": "dashboard.html", "content": "<h1>160</h1><svg></svg>"})
        return text("Listo: dashboard.html")

    local._script = script
    assert client.post("/api/chat", json={"message": "x", "skills": ["nope"]}).status_code == 400
    events = sse(client.post("/api/chat", json={"message": built["task"], "forge": built["blueprint"],
                                                "skills": built["skills"], "design_system": "spike"}))
    report = next(e for e in events if e["type"] == "forge_report")
    assert report["verified"] and [d["ok"] for d in report["deliverables"]] == [True]
    assert (home / "ws" / "dashboard.html").read_text() == "<h1>160</h1><svg></svg>"
    assert "# Skill: frontend-design" in systems["code"] and "# Skill:" not in systems["data"]  # research: no skill
    assert "# Design system:" in systems["code"]
    skill_events = [e for e in events if e["type"] == "skill"]
    assert skill_events and skill_events[0]["mode"] == "chosen" and skill_events[0]["names"] == ["frontend-design"]
