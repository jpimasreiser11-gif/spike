"""Reverse Studio routes (A20): the confirmation, the consent before an image leaves, placeholders for brand assets,
the saved file and its record, and (when a Chromium exists) the whole path from a page to a measured score."""

import json

import pytest
from fastapi.testclient import TestClient

from spike.core.types import StreamEvent
from spike.design import reverse, reverse_browser
from spike.design.reverse import ReverseError
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text
from tests.test_reverse import COPIED, PAGE, data_url, need_browser, png_bytes, site  # noqa: F401 - `site` is a fixture

IMAGE = data_url(png_bytes(120, 80, (240, 240, 240)))
REBUILT = """```html
<!doctype html><html><head><title>Page</title><style>body{margin:0;background:#f4f1ea;font:16px Georgia,serif}
header{display:flex;background:#1f3a5f;color:#fff;padding:12px 24px}h1{font-size:32px}</style></head>
<body><header><div style="width:120px;height:32px;background:#d9dde3"></div></header>
<main><h1>Lorem ipsum dolor</h1><button>Lorem ipsum</button></main></body></html>
```"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    with TestClient(create_app(state), client=("127.0.0.1", 50000)) as client:
        client.get("/api/providers")
        yield client, state, scripts


@pytest.fixture
def no_browser(monkeypatch):
    """The browser calls replaced by recorders: what the routes do around them is what these tests look at."""
    calls = {"capture": [], "measure": []}

    async def capture_page(**kwargs):
        calls["capture"].append(kwargs)
        return {"viewport": {"width": kwargs["width"], "height": kwargs["height"]}, "page": "#f4f1ea", "nodes": 6,
                "truncated": False, "names": ["Acme Cloud", "Acme Cloud logo", "Acme Cloud Inc"], "png": png_bytes(80, 60),
                "root": {"t": "body", "r": [0, 0, 800, 600], "s": {"margin": "0"}, "n": [
                    {"t": "header", "r": [0, 0, 800, 60], "s": {"display": "flex"}, "n": [
                        {"t": "img", "r": [10, 10, 120, 32], "s": {}, "k": "img"},
                        {"t": "svg", "r": [150, 10, 32, 32], "s": {}, "k": "svg"}]},
                    {"t": "h1", "r": [10, 80, 400, 40], "s": {"font-size": "32px"}, "c": 32}]}}

    async def measure(html, reference, width, height, timeout_s=60):
        calls["measure"].append({"html": html, "reference": reference, "size": (width, height)})
        return {"score": 0.8123, "metric": "1 - mean absolute RGB difference / 255", "width": width, "height": height}

    monkeypatch.setattr(reverse_browser, "capture_page", capture_page)
    monkeypatch.setattr(reverse_browser, "measure", measure)
    return calls


def vision_provider(client, **extra):
    body = {"preset": "openai", "api_key": "test-key", "model": "test-model", "allow_paid": True, "share_files": True,
            "capabilities": {"vision": True}, **extra}
    assert client.post("/api/providers", json=body).status_code == 200


def preview(client, source="url", **extra):
    body = {"authorized": True, "source": source, **extra}
    if source == "image":
        body.setdefault("image", IMAGE)
    elif source == "url":
        body.setdefault("url", "http://localhost:5173/")
    return client.post("/api/reverse/preview", json=body)


def generate(client, quote):
    return client.post("/api/reverse/generate", json={"preview_id": quote["id"]})


# ---------------------------------------------------------------- the confirmation
@pytest.mark.parametrize("authorized", [None, False, "true", "yes", 1, 0, "", []])
def test_without_the_confirmation_the_request_is_refused_and_nothing_runs(env, no_browser, authorized):
    client, state, scripts = env
    body = {"source": "url", "url": "http://localhost:5173/"}
    if authorized is not None:
        body["authorized"] = authorized
    response = client.post("/api/reverse/preview", json=body)
    assert response.status_code == 400 and response.json()["detail"] == "reverse_authorization"
    assert preview(client, "image", authorized=authorized).status_code == 400
    assert not scripts["spike-local"].requests and not no_browser["capture"] and not no_browser["measure"]
    assert not (state.home / "ws" / "reverse").exists()
    assert preview(client).status_code == 200  # the same request, confirmed


def test_the_confirmation_is_saved_with_the_result(env, no_browser):
    client, state, scripts = env
    quote = preview(client).json()
    assert quote["authorization"]["confirmed"] is True and quote["authorization"]["statement"] == reverse.STATEMENT
    scripts["spike-local"]._script = [text(REBUILT)]
    result = generate(client, quote).json()
    assert result["authorization"] == quote["authorization"] and result["authorization"]["reference"] == {
        "kind": "url", "value": "http://localhost:5173/"}
    saved = json.loads((state.home / "ws" / result["path"].replace(".html", ".json")).read_text(encoding="utf-8"))
    assert saved["authorization"] == quote["authorization"] and saved["source"] == "url"
    assert saved["authorization"]["at"] and saved["fidelity"]["score"] == 0.8123


def test_only_this_computer_may_use_it(env):
    _, state, _ = env
    other = TestClient(create_app(state), client=("192.0.2.1", 50000))
    assert other.post("/api/reverse/preview", json={"authorized": True, "source": "url", "url": "http://localhost/"}
                      ).status_code == 403
    assert other.get("/api/reverse").status_code == 403


# ---------------------------------------------------------------- an image needs a vision provider, or a URL
def test_an_image_with_a_text_only_model_says_it_needs_vision_or_a_url(env, no_browser):
    client, _, scripts = env
    response = preview(client, "image")
    assert response.status_code == 400 and response.json()["detail"] == "reverse_vision_required"
    assert not scripts["spike-local"].requests
    assert preview(client, "url").status_code == 200  # the same local model works from a page
    status = client.get("/api/reverse").json()
    local = next(p for p in status["providers"] if p["id"] == "spike-local")
    assert local["vision"] is False and local["local"] is True and status["statement"] == reverse.STATEMENT


# ---------------------------------------------------------------- no image leaves without consent
@pytest.mark.parametrize("extra,code", [({"allow_paid": False}, "reverse_provider_blocked"),
                                        ({"share_files": False}, "images_private"),
                                        ({"allow_paid": False, "share_files": False}, "images_private")])
def test_an_image_is_not_sent_unless_every_consent_is_given(env, no_browser, extra, code):
    client, _, scripts = env
    vision_provider(client, **extra)
    quote = preview(client, "image", provider_id="openai").json()
    assert quote["blocked"] == code and quote["egress"] is True and quote["sends"] == "image"
    assert not scripts["openai"].requests  # a preview sends nothing
    response = generate(client, quote)
    assert response.status_code == 403 and response.json()["detail"] == code
    assert not scripts["openai"].requests and not no_browser["measure"]


def test_a_provider_changed_after_the_preview_cannot_receive_the_image(env, no_browser):
    client, _, scripts = env
    vision_provider(client)
    quote = preview(client, "image", provider_id="openai").json()
    assert quote["blocked"] is None
    client.patch("/api/providers/openai", json={"allow_paid": False})  # the owner takes the permission back
    assert generate(client, quote).status_code == 409
    assert not scripts["openai"].requests
    quote = preview(client, "image", provider_id="openai").json()
    assert quote["blocked"] == "reverse_provider_blocked" and generate(client, quote).status_code == 403
    assert not scripts["openai"].requests


def test_an_image_goes_to_a_consented_vision_provider_once_after_the_preview(env, no_browser):
    client, state, scripts = env
    vision_provider(client)
    quote = preview(client, "image", provider_id="openai", own_text="Mi tienda", avoid=["Globex"]).json()
    assert quote["blocked"] is None and quote["egress"] is True and quote["provider"]["name"] == "OpenAI"
    assert quote["size"] == {"width": 120, "height": 80} and not scripts["openai"].requests
    scripts["openai"]._script = [text(REBUILT)]
    result = generate(client, quote)
    assert result.status_code == 200, result.text
    assert len(scripts["openai"].requests) == 1
    request = scripts["openai"].requests[0]
    assert request.messages[-1].images == [IMAGE] and request.messages[0].role == "system"
    prompt = request.messages[-1].content
    assert "120x80" in prompt and "Mi tienda" in prompt and "Globex" in prompt and "lorem" in prompt.lower()
    assert "Never copy a logo" in request.messages[0].content
    body = result.json()
    assert body["sent"] == {"what": "image", "to": "OpenAI", "remote": True}
    assert body["fidelity"] == {"measured": True, "score": 0.8123, "metric": "1 - mean absolute RGB difference / 255",
                                "width": 120, "height": 80, "against": "image"}
    assert no_browser["measure"][0]["reference"] == IMAGE and no_browser["measure"][0]["size"] == (120, 80)
    calls = client.get("/api/calls?remote=true").json()
    assert calls[0]["files_sent"] == 1 and calls[0]["files_withheld"] == 0
    assert generate(client, quote).status_code == 409  # a preview is used once


def test_a_local_vision_model_keeps_the_image_on_this_computer(env, no_browser):
    client, _, scripts = env
    client.patch("/api/providers/spike-local", json={"capabilities": {"vision": True}})
    quote = preview(client, "image").json()
    assert quote["egress"] is False and quote["blocked"] is None
    scripts["spike-local"]._script = [text(REBUILT)]
    assert generate(client, quote).json()["sent"]["remote"] is False
    assert scripts["spike-local"].requests[0].messages[-1].images == [IMAGE]


def test_a_remote_provider_not_allowed_files_gets_no_page_structure_either(env, no_browser):
    client, _, scripts = env
    vision_provider(client, share_files=False)
    quote = preview(client, "url", provider_id="openai").json()
    assert quote["sends"] == "structure" and quote["blocked"] == "reverse_files_blocked"
    assert generate(client, quote).status_code == 403
    assert not scripts["openai"].requests and not no_browser["capture"]  # not even the browser is started


# ---------------------------------------------------------------- brand assets become placeholders
def test_a_page_reaches_the_model_as_layout_with_placeholders_and_the_answer_is_cleaned(env, no_browser):
    client, state, scripts = env
    quote = preview(client).json()
    scripts["spike-local"]._script = [text(COPIED)]  # a model that copies everything it can
    result = generate(client, quote)
    assert result.status_code == 200, result.text
    sent = scripts["spike-local"].requests[0].messages[-1].content
    for leaked in ("Acme", "acme", "logo.png", "http", "keeps your files"):
        assert leaked not in sent, leaked
    assert "[image placeholder" in sent and "[graphic placeholder" in sent and "<img" not in sent
    assert scripts["spike-local"].requests[0].messages[-1].private == [sent]  # the page is the user's file content
    body = result.json()
    html = body["html"].replace(reverse.PLACEHOLDER_IMG, "").lower()
    for leaked in ("acme cloud", "acme.example", "http", "<script", "<svg", "<iframe", "<link", "onload", "@import",
                   "cdn.", "track."):
        assert leaked not in html, leaked
    assert "spike-placeholder" in body["html"] and body["names_removed"] == ["Acme Cloud Inc", "Acme Cloud"]
    assert body["removed"]["scripts"] == 1 and body["removed"]["images_and_graphics"] == 2
    assert body["fidelity"]["against"] == "page" and no_browser["capture"][0]["url"] == "http://localhost:5173/"
    assert no_browser["measure"][0]["reference"].startswith("data:image/png;base64,")


def test_the_users_own_text_is_used_and_its_names_are_not_removed(env, no_browser):
    client, _, scripts = env
    quote = preview(client, own_text="Acme Cloud, mi proyecto").json()
    scripts["spike-local"]._script = [text("<main><h1>Acme Cloud, mi proyecto</h1></main>")]
    body = generate(client, quote).json()
    assert "Acme Cloud, mi proyecto" in scripts["spike-local"].requests[0].messages[-1].content
    assert "<h1>Acme Cloud, mi proyecto</h1>" in body["html"] and body["names_removed"] == ["Acme Cloud Inc"]


def test_a_model_that_returns_no_page_gets_an_error_and_nothing_is_saved(env, no_browser):
    client, state, scripts = env
    quote = preview(client).json()
    scripts["spike-local"]._script = [text("Sorry, I can only describe pages in words.")]
    response = generate(client, quote)
    assert response.status_code == 422 and response.json()["detail"] == "reverse_invalid_output"
    assert not (state.home / "ws" / "reverse").exists() and not no_browser["measure"]


# ---------------------------------------------------------------- what is opened
@pytest.mark.parametrize("url", ["https://example.com/", "http://192.168.1.4:3000/", "file:///etc/passwd",
                                 "http://user:pw@localhost/", "http://localhost.evil.test/", ""])
def test_only_pages_on_this_computer_are_ever_opened(env, no_browser, url):
    client, _, scripts = env
    response = preview(client, "url", url=url)
    assert response.status_code == 400 and response.json()["detail"] == "reverse_url"
    assert not no_browser["capture"] and not scripts["spike-local"].requests


def test_a_page_of_the_project_is_read_from_its_folder_and_cannot_leave_it(env, no_browser):
    client, state, scripts = env
    project = state.store.create_project("Tienda")
    folder = state.project_files.folder(project["id"])
    (folder / "index.html").write_text("<h1>Hola</h1>", encoding="utf-8")
    quote = preview(client, "file", path="index.html", project_id=project["id"], width=900, height=500).json()
    assert quote["size"] == {"width": 900, "height": 500}
    scripts["spike-local"]._script = [text(REBUILT)]
    assert generate(client, quote).status_code == 200
    seen = no_browser["capture"][0]
    assert seen["folder"] == folder and seen["path"] == "index.html" and seen["url"] is None
    assert (seen["width"], seen["height"]) == (900, 500)
    for path in ("../index.html", "missing.html", "notes.txt", "/etc/passwd.html"):
        response = preview(client, "file", path=path, project_id=project["id"])
        assert response.status_code == 400 and response.json()["detail"] == "reverse_path", path
    assert preview(client, "file", path="index.html", project_id="nope").status_code == 404
    assert not (state.home / "projects" / "nope").exists()  # an unknown project is not created by asking for it


@pytest.mark.parametrize("image", ["not an image", "data:image/gif;base64,R0lGOD", "data:image/png;base64,AAAA",
                                   data_url(png_bytes(20, 20)), data_url(png_bytes(5000, 100))])
def test_a_bad_image_is_refused_before_any_provider_is_asked(env, no_browser, image):
    client, _, scripts = env
    vision_provider(client)
    response = preview(client, "image", image=image, provider_id="openai")
    assert response.status_code == 400
    assert response.json()["detail"] in ("image_invalid", "reverse_image_size")
    assert not scripts["openai"].requests


# ---------------------------------------------------------------- previews, failures, the browser
def test_previews_are_used_once_and_expire(env, no_browser, monkeypatch):
    from types import SimpleNamespace

    import spike.server.reverse_api as module
    client, _, scripts = env
    assert client.post("/api/reverse/generate", json={"preview_id": "nope"}).status_code == 409
    quote = preview(client).json()
    now = module.time.monotonic()
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now + 301, strftime=module.time.strftime))
    response = generate(client, quote)
    assert response.status_code == 409 and response.json()["detail"] == "reverse_expired"
    assert not scripts["spike-local"].requests and not no_browser["capture"]


def test_no_browser_means_no_page_but_an_image_still_works_without_a_score(env, no_browser, monkeypatch):
    client, state, scripts = env

    async def missing(**kwargs):
        raise ReverseError("reverse_browser_missing")

    async def missing_measure(*args, **kwargs):
        raise ReverseError("reverse_browser_missing")

    monkeypatch.setattr(reverse_browser, "capture_page", missing)
    monkeypatch.setattr(reverse_browser, "measure", missing_measure)
    response = generate(client, preview(client).json())
    assert response.status_code == 503 and response.json()["detail"] == "reverse_browser_missing"
    assert not scripts["spike-local"].requests  # the model is not asked for a page that could not be read
    client.patch("/api/providers/spike-local", json={"capabilities": {"vision": True}})
    scripts["spike-local"]._script = [text(REBUILT)]
    body = generate(client, preview(client, "image").json()).json()
    assert body["fidelity"] == {"measured": False, "reason": "reverse_browser_missing"} and body["html"]
    assert (state.home / "ws" / body["path"]).is_file()


def test_a_provider_that_fails_is_reported_without_saving(env, no_browser):
    client, state, scripts = env
    quote = preview(client).json()
    scripts["spike-local"]._script = lambda request: [StreamEvent(kind="error", text="boom with a secret")]
    response = generate(client, quote)
    assert response.status_code == 502 and response.json()["detail"] == "reverse_failed"
    assert "secret" not in response.text and not (state.home / "ws" / "reverse").exists()


# ---------------------------------------------------------------- saved and editable
def test_the_result_is_a_file_in_the_project_that_can_be_edited_afterwards(env, no_browser):
    client, state, scripts = env
    project = state.store.create_project("Tienda")
    quote = preview(client, project_id=project["id"]).json()
    scripts["spike-local"]._script = [text(REBUILT)]
    body = generate(client, quote).json()
    assert body["path"].startswith("reverse/reverse-") and body["path"].endswith(".html")
    assert body["project_id"] == project["id"] and body["filename"] == body["path"].split("/")[1]
    files = {f["path"] for f in client.get(f"/api/projects/{project['id']}/files").json()}
    assert {body["path"], body["path"][:-5] + ".json"} <= files
    on_disk = state.project_files.path(project["id"], body["path"]).read_text(encoding="utf-8")
    assert on_disk == body["html"] and on_disk.startswith("<!doctype html>") and "Lorem ipsum dolor" in on_disk
    assert "<style>" in on_disk and "<script" not in on_disk  # one file, its CSS inside
    edited = on_disk.replace("Lorem ipsum dolor", "Mis macetas")
    saved = client.put("/api/reverse/file", json={"project_id": project["id"], "path": body["path"], "html": edited})
    assert saved.status_code == 200 and saved.json()["size"] == len(edited.encode("utf-8"))
    assert "Mis macetas" in state.project_files.path(project["id"], body["path"]).read_text(encoding="utf-8")
    for bad in ("index.html", "reverse/../x.html", "reverse/a.txt", "reverse/UPPER.html", "../reverse/a.html"):
        response = client.put("/api/reverse/file", json={"project_id": project["id"], "path": bad, "html": "<p>x</p>"})
        assert response.status_code == 400, bad
    missing = client.put("/api/reverse/file", json={"project_id": project["id"], "path": "reverse/nothing.html", "html": "x"})
    assert missing.status_code == 404
    assert client.put("/api/reverse/file", json={"project_id": "nope", "path": body["path"], "html": "x"}).status_code == 404


def test_without_a_project_the_file_goes_to_the_workspace(env, no_browser):
    client, state, scripts = env
    scripts["spike-local"]._script = [text(REBUILT)]
    body = generate(client, preview(client).json()).json()
    target = state.home / "ws" / body["path"]
    assert target.is_file() and target.read_text(encoding="utf-8") == body["html"] and body["project_id"] is None
    assert client.get(f"/api/workspace/files/{body['path']}").status_code == 200
    assert client.put("/api/reverse/file", json={"path": body["path"], "html": "<p>mine</p>"}).status_code == 200
    assert target.read_text(encoding="utf-8") == "<p>mine</p>"


# ---------------------------------------------------------------- the whole path in a real browser
async def test_from_a_page_to_a_measured_score_with_a_real_browser(env, site):  # noqa: F811
    await need_browser()
    client, state, scripts = env
    quote = preview(client, url=site + "/", width=900, height=600).json()
    scripts["spike-local"]._script = [text(REBUILT)]
    body = generate(client, quote).json()
    sent = scripts["spike-local"].requests[0].messages[-1].content
    for leaked in ("Acme", "acme-logo", "keeps your files", "Pricing", "http"):
        assert leaked not in sent, leaked
    assert "[image placeholder" in sent and "display:grid" in sent and "#c2410c" in sent
    fidelity = body["fidelity"]
    assert fidelity["measured"] is True and fidelity["against"] == "page" and (fidelity["width"], fidelity["height"]) == (900, 600)
    assert 0.0 < fidelity["score"] < 1.0
    # the score is a measurement of this render: a different answer for the same page gives a different number
    scripts["spike-local"]._script = [text("<!doctype html><body style='margin:0;background:#000'><p>x</p>")]
    darker = generate(client, preview(client, url=site + "/", width=900, height=600).json()).json()["fidelity"]["score"]
    assert darker < fidelity["score"]
    scripts["spike-local"]._script = [text(PAGE)]
    same = generate(client, preview(client, url=site + "/", width=900, height=600).json()).json()
    assert same["fidelity"]["score"] > fidelity["score"] and "acme cloud" not in same["html"].lower()


async def test_an_image_is_scored_against_the_image_with_a_real_browser(env):
    await need_browser()
    client, state, scripts = env
    client.patch("/api/providers/spike-local", json={"capabilities": {"vision": True}})
    white = data_url(png_bytes(200, 120, (255, 255, 255)))
    scripts["spike-local"]._script = [text("<!doctype html><body style='margin:0;background:#fff'><p>x</p>")]
    close = generate(client, preview(client, "image", image=white).json()).json()["fidelity"]
    scripts["spike-local"]._script = [text("<!doctype html><body style='margin:0;background:#000'><p>x</p>")]
    far = generate(client, preview(client, "image", image=white).json()).json()["fidelity"]
    assert close["measured"] and far["measured"] and (close["width"], close["height"]) == (200, 120)
    assert close["score"] > 0.99 and far["score"] < 0.1 and close["against"] == "image"
