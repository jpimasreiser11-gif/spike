"""L2 release review of v0.1, the Low findings (docs/release/REVIEW-v0.1.md): each finding has tests here that failed
before its fix (37 of the 60 do; the rest are guards for what must keep working: ordinary tokens, redirects, placeholders).

L2  web_fetch resolved a name to check it and the HTTP client resolved it again (DNS rebinding in between)
L3  `spike models pull` without a SHA-256 from the Hub: tests/test_cli.py
L4  the proof package, the call log and a pack carried a provider's address with its userinfo, query and fragment
L5  a header typed with a literal secret value was stored in clear in the settings database
L6  the `url(` check of imported design tokens did not see CSS escapes
L7  `clean_path` refused `:` only in the first segment (Windows alternate data streams)
L8  GitHub Actions pinned by tag: tests/test_security_review_low.py and tests/test_real_model_check.py (source run)
"""

import io
import json
import re
import shutil
import socket
import ssl
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.connectors.manager import ConnectorManager
from spike.design.library import DesignError, check_tokens
from spike.packs import export_pack
from spike.projects import ProjectError, clean_path
from spike.proof import build_proof
from spike.runtime.paths import is_git_name
from spike.runtime.urls import strip_url_secrets
from spike.server.app import create_app
from spike.server.state import AppState
from spike.store.db import Store
from spike.store.secrets import SecretStore
from spike.tools import builtin
from spike.tools.builtin import WebFetch
from tests.helpers import ScriptedProvider

ROOT = Path(__file__).resolve().parents[1]
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")


# ------------------------------------------------------------------------------------------------ L2: DNS rebinding
class Dns:
    """The resolver for named hosts: each lookup of a name takes the next answer (the last one repeats). Anything
    else (an IP literal) goes to the real resolver, a name with no answer does not resolve."""

    def __init__(self, monkeypatch, **answers: list[list[str]]):
        self.answers = {name.replace("_", "."): [list(a) for a in queue] for name, queue in answers.items()}
        self.lookups: list[str] = []
        real = socket.getaddrinfo

        def lookup(host, port, *args, **kwargs):
            self.lookups.append(host)
            if host not in self.answers:
                if host.replace(".", "").isdigit() or ":" in host:
                    return real(host, port, *args, **kwargs)
                raise socket.gaierror("no such name")
            queue = self.answers[host]
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
            return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in answer]

        monkeypatch.setattr(socket, "getaddrinfo", lookup)


def recording_client(seen: list[httpx.Request], fail: set[str] = frozenset()) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host in fail:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, text="page", headers={"content-type": "text/plain"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_web_fetch_connects_to_the_address_it_checked(monkeypatch):
    """The name answers with a public address once and with 127.0.0.1 at the next lookup (rebinding). The request must
    go to the address that was checked, with the name kept in the Host header."""
    dns = Dns(monkeypatch, rebind_example=[["93.184.216.34"], ["127.0.0.1"]])
    seen: list[httpx.Request] = []
    result = await WebFetch(client=recording_client(seen)).run({"url": "http://rebind.example/page?x=1"})
    assert result.ok and result.content.startswith("[HTTP 200] http://rebind.example/page?x=1")
    assert [(r.url.host, r.url.path, r.url.query) for r in seen] == [("93.184.216.34", "/page", b"x=1")]
    assert seen[0].headers["host"] == "rebind.example"
    assert dns.lookups.count("rebind.example") == 1  # resolved once; nothing else gets to resolve it again


async def test_web_fetch_keeps_the_name_for_tls_and_the_port_in_host(monkeypatch):
    Dns(monkeypatch, rebind_example=[["93.184.216.34"], ["127.0.0.1"]])
    seen: list[httpx.Request] = []
    await WebFetch(client=recording_client(seen)).run({"url": "https://rebind.example:8443/"})
    assert (seen[0].url.host, seen[0].url.port, seen[0].url.scheme) == ("93.184.216.34", 8443, "https")
    assert seen[0].headers["host"] == "rebind.example:8443"
    assert seen[0].extensions["sni_hostname"] == "rebind.example"  # the handshake sends and verifies the name
    seen.clear()
    Dns(monkeypatch, rebind_example=[["93.184.216.34"], ["127.0.0.1"]])
    await WebFetch(client=recording_client(seen)).run({"url": "http://rebind.example/"})
    assert "sni_hostname" not in seen[0].extensions


async def test_web_fetch_tries_the_next_checked_address_and_only_those(monkeypatch):
    Dns(monkeypatch, two_example=[["2606:4700::1111", "93.184.216.34"], ["127.0.0.1"]])
    seen: list[httpx.Request] = []
    result = await WebFetch(client=recording_client(seen, fail={"2606:4700::1111"})).run({"url": "http://two.example/"})
    assert result.ok and [r.url.host for r in seen] == ["2606:4700::1111", "93.184.216.34"]
    seen.clear()
    Dns(monkeypatch, two_example=[["2606:4700::1111", "93.184.216.34"], ["127.0.0.1"]])
    result = await WebFetch(client=recording_client(seen, fail={"2606:4700::1111", "93.184.216.34"})).run(
        {"url": "http://two.example/"})
    assert result.ok is False and "ConnectError" in result.content and len(seen) == 2


async def test_web_fetch_refuses_a_name_with_any_address_that_is_not_public(monkeypatch):
    Dns(monkeypatch, mixed_example=[["93.184.216.34", "10.0.0.5"]], gone_example=[[]])
    seen: list[httpx.Request] = []
    for url in ("http://mixed.example/", "http://gone.example/", "http://nothing.example/"):
        result = await WebFetch(client=recording_client(seen)).run({"url": url})
        assert result.ok is False and "blocked" in result.content
    assert seen == []


async def test_web_fetch_does_not_follow_a_redirect_and_the_next_call_is_checked_again(monkeypatch):
    """A redirect is handed back to the model, and fetching its target is a new call through the same check."""
    Dns(monkeypatch, hop_example=[["93.184.216.34"]])
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await WebFetch(client=client).run({"url": "http://hop.example/"})
    assert result.ok is False and "redirect to http://169.254.169.254/" in result.content and len(seen) == 1
    again = await WebFetch(client=client).run({"url": "http://169.254.169.254/latest/meta-data/"})
    assert again.ok is False and "blocked" in again.content and len(seen) == 1


class Page(BaseHTTPRequestHandler):
    seen: list[tuple[str, str]] = []

    def do_GET(self):
        Page.seen.append((self.path, self.headers.get("Host", "")))
        body = b"hello from the checked address"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(handler=Page):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def test_web_fetch_reaches_the_checked_address_on_a_real_socket(monkeypatch):
    """No client is injected: the real HTTP client, a real listener, and a name whose second lookup would fail."""
    for var in PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    server = serve()
    port = server.server_address[1]
    Page.seen = []
    monkeypatch.setattr(builtin, "_is_public_address", lambda ip: True)  # the listener is on loopback
    dns = Dns(monkeypatch, rebind_test=[["127.0.0.1"], []])  # the second lookup finds nothing: the client must not ask
    try:
        result = await WebFetch().run({"url": f"http://rebind.test:{port}/page"})
    finally:
        server.shutdown()
    assert result.ok and "hello from the checked address" in result.content, result.content
    assert Page.seen == [("/page", f"rebind.test:{port}")] and dns.lookups.count("rebind.test") == 1


def tls_listener(tmp_path, certificate_name: str):
    """A loopback HTTPS listener whose certificate is for `certificate_name` only; returns (server, certificate path,
    the server names the clients asked for)."""
    if not shutil.which("openssl"):
        pytest.skip("openssl is needed to make the test certificate")
    key, crt = tmp_path / "key.pem", tmp_path / "crt.pem"
    made = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out",
                           str(crt), "-days", "2", "-subj", f"/CN={certificate_name}",
                           "-addext", f"subjectAltName=DNS:{certificate_name}"], capture_output=True)
    if made.returncode:
        pytest.skip("this openssl cannot make the test certificate")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(crt, key)
    names: list[str | None] = []
    context.sni_callback = lambda sock, name, ctx: names.append(name)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, crt, names


async def test_web_fetch_verifies_the_certificate_against_the_name_not_the_address(tmp_path, monkeypatch):
    """https to the checked address still sends the name as SNI and accepts only a certificate that is for the name."""
    for var in PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(builtin, "_is_public_address", lambda ip: True)  # the listener is on loopback
    server, crt, names = tls_listener(tmp_path, "secure.test")
    monkeypatch.setenv("SSL_CERT_FILE", str(crt))  # the only certificate the client trusts
    port = server.server_address[1]
    Dns(monkeypatch, secure_test=[["127.0.0.1"], []], other_test=[["127.0.0.1"], []])
    Page.seen = []
    try:
        ok = await WebFetch().run({"url": f"https://secure.test:{port}/page"})
        assert ok.ok and "hello from the checked address" in ok.content, ok.content
        assert names == ["secure.test"] and Page.seen == [("/page", f"secure.test:{port}")]
        wrong = await WebFetch().run({"url": f"https://other.test:{port}/page"})  # same listener, certificate for another name
        assert wrong.ok is False and "CERTIFICATE_VERIFY_FAILED" in wrong.content, wrong.content
        assert Page.seen == [("/page", f"secure.test:{port}")]  # nothing was sent after the failed handshake
    finally:
        server.shutdown()


def test_a_proxy_in_the_environment_is_detected_per_url(monkeypatch):
    for var in PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    assert builtin._via_proxy(httpx.URL("https://example.org/")) is False
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp:3128")
    assert builtin._via_proxy(httpx.URL("https://example.org/")) is True
    assert builtin._via_proxy(httpx.URL("http://example.org/")) is False  # only https goes through this one
    monkeypatch.setenv("NO_PROXY", "example.org")
    assert builtin._via_proxy(httpx.URL("https://example.org/")) is False


async def test_behind_a_proxy_a_name_that_changes_between_lookups_is_refused(monkeypatch):
    """The proxy resolves the name itself and cannot be pinned, so SPIKE looks it up again right before and refuses
    when the answer is not the one it checked."""
    for var in PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    got: list[str] = []

    class Proxy(BaseHTTPRequestHandler):
        def do_GET(self):
            got.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = serve(Proxy)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{server.server_address[1]}")
    try:
        Dns(monkeypatch, shifty_example=[["93.184.216.34"], ["93.184.216.35"]], steady_example=[["93.184.216.34"]])
        refused = await WebFetch().run({"url": "http://shifty.example/"})
        assert refused.ok is False and "blocked" in refused.content and got == []
        served = await WebFetch().run({"url": "http://steady.example/"})
        assert served.ok and got == ["http://steady.example/"]  # the proxy is asked for the name, as always
    finally:
        server.shutdown()


# ------------------------------------------------------------------------------------------------ L4: urls in records
@pytest.mark.parametrize("url,clean", [
    ("https://me:sk-live-123@api.example.com/v1?api_key=sk-live-456#frag", "https://api.example.com/v1"),
    ("https://api.example.com:8443/v1/", "https://api.example.com:8443/v1/"),
    ("http://localhost:11434/v1", "http://localhost:11434/v1"),
    ("http://user@[::1]:8080/v1?x=1", "http://[::1]:8080/v1"),
    ("https://a:p@ss@host.example/v1", "https://host.example/v1"),
    ("https://host.example?key=abc", "https://host.example"),
    ("https://host.example#abc", "https://host.example"),
    ("", ""), ("no url here", "no url here"), ("localhost:11434/v1?x=1", "localhost:11434/v1?x=1"),
])
def test_a_url_loses_its_userinfo_query_and_fragment(url, clean):
    assert strip_url_secrets(url) == clean


def test_urls_inside_a_message_are_stripped_and_the_message_is_kept():
    text = "Client error for url 'https://u:k@h.example/v1/chat?key=abc' (retry; see http://h.example/docs#x), done."
    assert strip_url_secrets(text) == "Client error for url 'https://h.example/v1/chat' (retry; see http://h.example/docs), done."


SECRET_URL = "https://me:sk-live-123@api.example.com/v1?api_key=sk-live-456#frag"


def proof_zip(**overrides) -> zipfile.ZipFile:
    conv = {"id": "c1", "title": "t", "mode": "auto", "provider_id": "p1", "project_id": None, "created": 1.0}
    calls = [{"provider_id": "p1", "provider": "Mine", "model": "m", "status": "error", "tokens_in": 1, "tokens_out": 0,
              "cost": None, "estimated": False, "ts": 1.0, "files_sent": 0, "files_withheld": 0,
              "detail": f"HTTP 502 from {SECRET_URL}"}]
    providers = [{"id": "p1", "kind": "openai", "name": "Mine", "base_url": SECRET_URL, "model": "m", "paid": False}]
    blob = build_proof(conv, [], calls, [], providers, {}, **overrides)
    return zipfile.ZipFile(io.BytesIO(blob))


def test_the_proof_package_has_no_credentials_from_a_provider_address():
    zf = proof_zip()
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["providers"][0]["base_url"] == "https://api.example.com/v1"
    for name in zf.namelist():
        data = zf.read(name).decode("utf-8", "replace")
        assert "sk-live" not in data and "api_key" not in data, name
    assert json.loads(zf.read("calls.json"))[0]["detail"] == "HTTP 502 from https://api.example.com/v1"


def test_the_call_log_stores_and_returns_addresses_without_credentials(tmp_path):
    store = Store(tmp_path / "spike.db")
    store.log_call("p1", "Mine", "error", detail=f"HTTP 502 from {SECRET_URL}", conversation_id="c1")
    assert store.calls()[0]["detail"] == "HTTP 502 from https://api.example.com/v1"
    assert store.calls_for("c1")[0]["detail"] == "HTTP 502 from https://api.example.com/v1"
    raw = store._conn.execute("SELECT detail FROM calls").fetchone()[0]
    assert "sk-live" not in raw  # not even on disk
    store._conn.execute("INSERT INTO calls (ts, provider_id, provider, status, detail) VALUES (1,'p','P','error',?)",
                        (f"old row {SECRET_URL}",))  # written by an earlier version
    assert all("sk-live" not in c["detail"] for c in store.calls())


def test_a_pack_exports_connector_addresses_without_userinfo_or_query():
    blob = export_pack([], [{"id": "web", "name": "Web", "transport": "http", "url": "https://u:k@mcp.example/sse?key=abc",
                             "headers": {"Authorization": "Bearer x"}}], [])
    pack = json.loads(zipfile.ZipFile(io.BytesIO(blob)).read("pack.json"))
    assert pack["connectors"][0]["url"] == "https://mcp.example/sse" and "headers" not in pack["connectors"][0]


# ------------------------------------------------------------------------------------------------ L5: header secrets
@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    store = Store(tmp_path / "spike.db")
    secrets = SecretStore(tmp_path / "secrets.json")
    return ConnectorManager(store, secrets, tmp_path / "ws", tmp_path / "connectors", catalog=[]), store, secrets, tmp_path


def database_bytes(folder: Path) -> bytes:
    return b"".join(p.read_bytes() for p in folder.glob("spike.db*"))


def http_connector(**extra) -> dict:
    return {"id": "web", "name": "Web", "transport": "http", "url": "https://mcp.example/mcp", **extra}


def test_a_literal_secret_header_goes_to_the_key_store_not_to_the_database(conn):
    manager, store, secrets, home = conn
    manager.add_custom(http_connector(headers={"Authorization": "Bearer sk-live-123", "X-Api-Key": "k-456",
                                               "Accept": "application/json", "X-Team": "{TEAM}"}))
    assert b"sk-live-123" not in database_bytes(home) and b"k-456" not in database_bytes(home)
    row = store.get_setting("custom_connectors")[0]
    assert row["headers"] == {"Authorization": "{HEADER_AUTHORIZATION}", "X-Api-Key": "{HEADER_X_API_KEY}",
                              "Accept": "application/json", "X-Team": "{TEAM}"}  # only credential-looking names move
    assert secrets.get("connector:web:HEADER_AUTHORIZATION") == "Bearer sk-live-123"
    assert secrets.get("connector:web:HEADER_X_API_KEY") == "k-456"
    assert {s["name"] for s in row["secrets"]} == {"HEADER_AUTHORIZATION", "HEADER_X_API_KEY"}
    view = manager.public(manager.get("web"))
    assert view["secrets_set"] == {"HEADER_AUTHORIZATION": True, "HEADER_X_API_KEY": True}
    assert "sk-live-123" not in json.dumps(view) and view["header_names"] == ["Accept", "Authorization", "X-Api-Key", "X-Team"]


def test_the_stored_header_still_reaches_the_server_with_its_value(conn):
    manager, *_ = conn
    manager.add_custom(http_connector(headers={"Authorization": "Bearer sk-live-123", "Accept": "application/json"}))
    sent = manager._client(manager.get("web")).transport.headers
    assert sent == {"Authorization": "Bearer sk-live-123", "Accept": "application/json"}


def test_rows_stored_by_an_earlier_version_are_migrated_when_read(conn):
    manager, store, secrets, _ = conn
    store.set_setting("custom_connectors", [http_connector(headers={"Cookie": "session=abc123", "Accept": "text/plain"})])
    assert manager.get("web").headers == {"Cookie": "{HEADER_COOKIE}", "Accept": "text/plain"}
    assert "abc123" not in json.dumps(store.get_setting("custom_connectors"))
    assert secrets.get("connector:web:HEADER_COOKIE") == "session=abc123"
    assert manager._client(manager.get("web")).transport.headers["Cookie"] == "session=abc123"
    before = store.get_setting("custom_connectors")
    manager.definitions()
    assert store.get_setting("custom_connectors") == before  # nothing more to move the second time


def test_a_header_built_from_a_placeholder_is_left_alone(conn):
    manager, store, secrets, _ = conn
    row = http_connector(headers={"Authorization": "Bearer {TOKEN}"}, secrets=[{"name": "TOKEN", "label": "Token"}])
    manager.add_custom(row)
    assert store.get_setting("custom_connectors")[0]["headers"] == {"Authorization": "Bearer {TOKEN}"}
    assert not secrets.has("connector:web:HEADER_AUTHORIZATION")


def test_a_key_store_that_refuses_leaves_the_row_readable_and_unchanged(conn, monkeypatch):
    manager, store, secrets, _ = conn
    store.set_setting("custom_connectors", [http_connector(headers={"Authorization": "Bearer legacy"})])

    def refuse(name, value):
        raise RuntimeError("keychain locked")

    monkeypatch.setattr(secrets, "set", refuse)
    assert manager.get("web").headers == {"Authorization": "Bearer legacy"}  # still works; tried again at the next read
    assert store.get_setting("custom_connectors")[0]["headers"] == {"Authorization": "Bearer legacy"}
    with pytest.raises(ValueError, match="key store"):
        manager.add_custom(http_connector(id="other", headers={"Authorization": "Bearer new"}))
    assert manager.get("other") is None


async def test_removing_the_connector_removes_its_header_secrets(conn):
    manager, store, secrets, _ = conn
    manager.add_custom(http_connector(headers={"Authorization": "Bearer sk-live-123"}))
    await manager.remove_custom("web")
    assert not secrets.has("connector:web:HEADER_AUTHORIZATION") and store.get_setting("custom_connectors") == []


# ------------------------------------------------------------------------------------------------ L6: token escapes
@pytest.mark.parametrize("css", [
    ":root { --bg: u\\72l(https://e.example/a.png); }",             # \72 is r
    ":root { --bg: \\75rl(https://e.example/a.png); }",             # \75 is u
    ":root { --bg: \\000075 rl(https://e.example/a.png); }",        # six digits, the space ends the escape
    ":root { --bg: U\\52 L(https://e.example/a.png); }",
    ":root { --bg: \\75\nrl(https://e.example/a.png); }",           # the escape ends at a line break
    ":root { --a: 1; } \\40import 'https://e.example/x.css';",
    ":root { --a: 1; } @\\69mport 'https://e.example/x.css';",
    ":root { --a: expr\\65ssion(alert(1)); }",
    ":root { --a: java\\73 cript:alert(1); }",
    ":root { --a: image-set('https://e.example/a.png' 1x); }",      # a string loads without `url(`
    # guards for a check that reads through comments and escapes: neither may hide the call from it
    ":root { --a: \\/* url(https://e.example/a.png) */ 1; }",       # an escaped slash is not the start of a comment
    ':root { --a: "/*"; --b: url(https://e.example/a.png); --c: "*/"; }',  # nor is a comment inside strings
])
def test_tokens_with_css_escapes_cannot_hide_what_the_check_refuses(css):
    with pytest.raises(DesignError):
        check_tokens(css)


@pytest.mark.parametrize("css", [
    ":root { --font: 'Inter Tight', sans-serif; --quote: \"\\201C\"; --space: 4px; --bg: #fff; }",
    ":root { /* links are not used here */ --a: calc(1px + 2px); }",
    "@media (prefers-color-scheme: dark) { :root { --bg: #111; } }",
    ":root { --path: 'C:\\\\fonts'; --id: \\31 23; }",
])
def test_ordinary_tokens_with_escapes_still_pass(css):
    assert check_tokens(css) == css


# ------------------------------------------------------------------------------------------------ L7: colons in paths
@pytest.mark.parametrize("name", ["dir/file.txt:stream", "a/b/c.txt::$DATA", "dir\\file.txt:stream", "C:/windows/x",
                                  "C:\\x", "a/C:/x", "docs/.git::$INDEX_ALLOCATION/config", "x/y:z/w.txt"])
def test_a_project_path_has_no_colon_in_any_segment(name):
    with pytest.raises(ProjectError):
        clean_path(name)
    assert clean_path("docs/notes v2/readme.md").as_posix() == "docs/notes v2/readme.md"


@pytest.mark.parametrize("name", [".git::$INDEX_ALLOCATION", ".GIT:stream", "git~1:x", ".git.:x"])
def test_a_git_folder_reached_through_a_data_stream_name_is_still_git(name):
    assert is_git_name(name)


def test_a_file_upload_and_an_archive_cannot_name_a_data_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")
    state = AppState(home=tmp_path, provider_factory=lambda cfg: local)
    client = TestClient(create_app(state))
    pid = client.post("/api/projects", json={"name": "p"}).json()["id"]
    assert client.put(f"/api/projects/{pid}/files/dir/file.txt:stream", content=b"x").status_code == 400
    assert client.put(f"/api/projects/{pid}/files/dir/file.txt", content=b"x").status_code == 200
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project.json", json.dumps({"format": "spike-project", "version": 1, "project": {
            "name": "shared", "instructions": "", "mode": "auto", "design": ""}, "conversations": []}))
        z.writestr("files/dir/a.txt:stream", "hidden")
    assert client.post("/api/projects/import", content=buf.getvalue()).status_code == 400
    assert len(client.get("/api/projects").json()) == 1  # only the first project exists


# ------------------------------------------------------------------------------------------------ L8: pinned actions
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+?)(?:\s+#\s*(?P<comment>.*))?\s*$")


def workflow_uses() -> list[tuple[str, str, str | None]]:
    found = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if (m := USES.match(line)):
                found.append((f"{path.name}:{number}", m["ref"], m["comment"]))
    return found


def test_every_action_is_pinned_to_a_full_commit_with_its_tag_in_a_comment():
    uses = workflow_uses()
    assert len(uses) >= 40  # the scan finds the steps (a regex that matched nothing would pass vacuously)
    for where, ref, comment in uses:
        name, _, version = ref.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", version), f"{where}: {ref} is not pinned to a commit"
        assert comment and re.fullmatch(r"v\d+(\.\d+){0,2}", comment.strip()), f"{where}: {ref} has no '# vN' comment"


def test_the_same_action_has_the_same_commit_in_every_workflow():
    pins: dict[tuple[str, str], set[str]] = {}
    for _, ref, comment in workflow_uses():
        name, _, sha = ref.partition("@")
        pins.setdefault((name, comment.strip()), set()).add(sha)
    assert all(len(shas) == 1 for shas in pins.values()), pins
