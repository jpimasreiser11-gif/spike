"""Spike Design (C4): the bundled design systems, importing one, its prompt section, and its use in chats and
projects."""

import io
import json
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from spike.design.library import BUNDLED, DesignError, DesignLibrary, design_prompt, preview_html
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text

SHIPPED = {"spike", "neutral-modern", "minimal", "clean", "modern", "refined", "mono", "flat", "editorial",
           "publication", "brutalism", "neobrutalism", "glassmorphism", "claymorphism", "corporate", "friendly",
           "retro", "spacious", "bold", "paper", "professional"}
# companies whose look open-design also imitates: none of those systems is shipped
BRANDS = re.compile(r"\b(airbnb|apple inc|stripe|linear|vercel|notion|google|bloomberg|figma|spotify|tesla|claude|"
                    r"openai|anthropic|nike|uber|github|heroku|material design)\b", re.IGNORECASE)
DESIGN = "# Design System for Acme Café\n\n> Category: Brand\n> Warm and cosy.\n\n- **Primary:** `#AA3300` — CTA.\n"
TOKENS = ":root {\n  --bg: #fffaf0;\n  --fg: #222222;\n  --accent: #aa3300;\n}\n"


def zipped(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_the_bundled_systems_are_generic_and_complete(tmp_path):
    lib = DesignLibrary(tmp_path / "user")
    assert lib.errors == [] and {d.id for d in lib.all()} == SHIPPED
    assert lib.all()[0].id == "spike" and (BUNDLED / "LICENSE-open-design").is_file()
    for ds in lib.all():
        assert not BRANDS.search(ds.design() + ds.tokens()), ds.id
        names = {c["name"] for c in ds.colors()}
        assert {"bg", "fg", "accent"} <= names, ds.id
    minimal = lib.get("minimal")
    assert (minimal.name, minimal.category) == ("Minimal", "Modern & Minimal")
    assert lib.get("neutral-modern").name == "Neutral Modern"


def test_the_prompt_carries_the_tokens_and_fits_the_budget(tmp_path):
    lib = DesignLibrary(tmp_path / "user")
    full = design_prompt(lib.get("neutral-modern"), 3000)
    assert full.startswith("# Design system: Neutral Modern") and "--accent:" in full and "/*" not in full
    assert lib.get("neutral-modern").design().strip().splitlines()[-1] in full  # all of DESIGN.md fits in 3000
    short = design_prompt(lib.get("neutral-modern"), 300)
    assert short.endswith("[…design system cut to fit the context window]") and "--accent:" in short
    assert len(short) < len(full)


def test_importing_a_design_md_or_a_zip(tmp_path):
    lib = DesignLibrary(tmp_path / "user")
    acme = lib.import_blob(DESIGN.encode())[0]
    assert (acme.id, acme.name, acme.category, acme.source) == ("acme-cafe", "Acme Café", "Brand", "user")
    assert acme.colors() == [{"name": "Primary", "value": "#aa3300"}] and not acme.to_dict()["has_tokens"]
    two = lib.import_blob(zipped({"pack/warm/DESIGN.md": DESIGN, "pack/warm/tokens.css": TOKENS,
                                  "cool/DESIGN.md": "# Cool\n", "../evil/DESIGN.md": "# Evil\n"}))
    assert sorted(d.id for d in two) == ["cool", "warm"]
    assert lib.get("warm").tokens() == TOKENS and lib.get("warm").colors()[0] == {"name": "bg", "value": "#fffaf0"}
    assert [d.id for d in lib.import_blob(zipped({"DESIGN.md": "# Top Level\n"}))] == ["top-level"]
    mine = lib.import_blob(zipped({"minimal/DESIGN.md": "# My minimal\n"}))[0]
    assert lib.get("minimal").source == "user" and mine.name == "My minimal"  # overrides the bundled one
    lib.delete("minimal")
    assert lib.get("minimal").source == "bundled"
    with pytest.raises(DesignError, match="only design systems you imported"):
        lib.delete("minimal")


@pytest.mark.parametrize("files, error", [
    ({"x/DESIGN.md": "no title here"}, "title line"),
    ({"x/DESIGN.md": "# X\n", "x/tokens.css": ":root { --bg: url(https://e.com/a.png); }"}, "url\\("),
    ({"x/DESIGN.md": "# X\n", "x/tokens.css": ":root{--a:#fff}</style><script>alert(1)</script>"}, "</style"),
    ({"x/DESIGN.md": "# X\n", "x/tokens.css": "body { color: red }"}, "custom properties"),
    ({"notes.txt": "hi"}, "no DESIGN.md"),
    ({"x/DESIGN.md": "# X\n" + "a" * 70_000}, "64 KB"),
])
def test_bad_imports_are_refused(tmp_path, files, error):
    with pytest.raises(DesignError, match=error):
        DesignLibrary(tmp_path / "user").import_blob(zipped(files))


def test_the_preview_escapes_imported_text(tmp_path):
    lib = DesignLibrary(tmp_path / "user")
    ds = lib.import_blob(b"# <script>alert(1)</script>\n\n> <img src=x onerror=alert(2)>\n")[0]
    page = preview_html(ds)
    assert "<script>alert" not in page and "<img src=x" not in page and "&lt;script&gt;" in page
    assert "--accent: #" in preview_html(lib.get("spike"))


# ---------------------------------------------------------------- the app
@pytest.fixture
def env(tmp_path, monkeypatch):
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    return TestClient(create_app(AppState(home=tmp_path, provider_factory=factory))), local


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_the_api_lists_imports_previews_and_deletes(env):
    client, _ = env
    listed = client.get("/api/design-systems").json()
    assert listed[0]["id"] == "spike" and len(listed) == len(SHIPPED) and "design" not in listed[0]
    one = client.get("/api/design-systems/minimal").json()
    assert one["design"].startswith("# Design System Inspired by Minimal") and "--bg:" in one["tokens"]
    assert "<h1>Minimal</h1>" in client.get("/api/design-systems/minimal/preview").json()["html"]
    assert client.get("/api/design-systems/nope").status_code == 404
    imported = client.post("/api/design-systems/import", content=zipped({"acme/DESIGN.md": DESIGN,
                                                                         "acme/tokens.css": TOKENS})).json()
    assert [d["id"] for d in imported["imported"]] == ["acme"]
    bad = client.post("/api/design-systems/import", content=b"no title")
    assert bad.status_code == 400 and "title line" in bad.json()["detail"]
    assert client.delete("/api/design-systems/minimal").status_code == 400
    assert client.delete("/api/design-systems/acme").json()["ok"]
    assert client.get("/api/design-systems/acme").status_code == 404


def test_chats_and_projects_use_the_design_system(env):
    client, local = env
    local._script = lambda req: text("ok")
    r = client.post("/api/chat", json={"message": "Hazme una landing", "design_system": "minimal"})
    assert "# Design system: Minimal" in local.requests[-1].messages[0].content
    conv = events_of(r)[0]["id"]
    stored = client.get(f"/api/conversations/{conv}").json()["messages"][-1]
    assert stored["meta"]["design"] == {"id": "minimal", "name": "Minimal"}
    assert client.post("/api/chat", json={"message": "x", "design_system": "nope"}).status_code == 400

    assert client.post("/api/projects", json={"name": "Web", "design": "nope"}).status_code == 400
    project = client.post("/api/projects", json={"name": "Web", "design": "spike"}).json()
    assert project["design"] == "spike"
    client.post("/api/chat", json={"message": "Una página", "project_id": project["id"]})
    assert "# Design system: SPIKE" in local.requests[-1].messages[0].content
    client.post("/api/chat", json={"message": "Otra", "project_id": project["id"], "design_system": "brutalism"})
    assert "# Design system: Brutalism" in local.requests[-1].messages[0].content
    client.post("/api/chat", json={"message": "Sin diseño", "project_id": project["id"], "design_system": "none"})
    assert "# Design system" not in local.requests[-1].messages[0].content
    client.post("/api/chat", json={"message": "Sin proyecto"})
    assert "# Design system" not in local.requests[-1].messages[0].content

    assert client.patch(f"/api/projects/{project['id']}", json={"design": "editorial"}).json()["design"] == "editorial"
    blob = client.get(f"/api/projects/{project['id']}/export").content
    copy = client.post("/api/projects/import", content=blob).json()
    assert copy["design"] == "editorial"
