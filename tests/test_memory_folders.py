"""Opt-in folder indexing for Neural Memory: nothing without a folder, rules, limits, links that stay inside,
changed files only, progress through the API, and forgetting a folder leaves nothing in the database file."""

import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.memory import folders as folders_module
from spike.memory.folders import DEFAULT_EXCLUDE, DEFAULT_INCLUDE, FolderError, FolderIndex, matches, within
from spike.memory.service import MemoryService, memory_section
from spike.memory.store import GLOBAL, MemoryStore
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text
from tests.test_memory import ConceptEmbedder, _ret, no_embedder

SECRET = "zanahoriasecreta42"
LOCAL = ("127.0.0.1", 50_000)  # a request from this computer; the test client's own name is not one


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "home" / "memory.db")
    yield s
    s.close()


def write(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def tree(root: Path) -> Path:
    return write(root, {
        "notas/plan.md": "# Plan\n\nEl cliente Norte paga a 60 días. Código interno: marmota77.",
        "notas/ideas.txt": "Ideas sueltas sobre la facturación electrónica.",
        "src/app.py": "def total(x):\n    return x * 1.21  # IVA general\n",
        "web/index.html": "<html><body><h1>Portada</h1><p>Texto visible</p><script>var oculto=1</script></body></html>",
        ".git/config": "[core] token=ghp_hidden_token",
        ".hidden/nota.md": "oculta",
        ".env": "API_KEY=hidden-env",
        "node_modules/lib/readme.md": "paquete externo",
        "venv/pyvenv.cfg": "home = /usr/bin",
        "venv/lib/x.py": "print('venv')",
        "mi_entorno/pyvenv.cfg": "home = /usr/bin",  # a virtual environment with another name
        "mi_entorno/lib/y.md": "dentro de un entorno virtual",
        "secrets.json": '{"clave": "no"}',
        "build/out.md": "salida de build",
        "foto.png": b"\x89PNG\r\n\x1a\n\x00\x00",
        "raro.txt": b"abc\x00def",  # a binary file that is called .txt
    })


async def run(index: FolderIndex, folder_id: str, force: bool = False):
    job = index.queue(folder_id, force)
    await index.run(job)
    return job


def sources(store) -> set[str]:
    return {m.source for m in store.list(kind="document", limit=1000)}


# ------------------------------------------------------------------------------------------- the rules
def test_glob_rules_match_names_and_relative_paths_ignoring_case():
    assert matches(["node_modules"], "node_modules", "a/node_modules", directory=True)
    assert matches([".*"], ".git", ".git", directory=True) and not matches([".*"], "notes.md", "notes.md")
    assert matches(["*.MD"], "plan.md", "notas/plan.md") and not matches(["*.md"], "plan.mdx", "plan.mdx")
    assert matches(["drafts/*"], "a.md", "drafts/sub/a.md") and not matches(["drafts/*"], "a.md", "final/a.md")
    assert matches(["drafts/*"], "drafts", "drafts", directory=True)  # a folder the pattern covers is not entered
    assert not matches([""], "a.md", "a.md")


def test_within_is_a_whole_path_prefix():
    assert within(Path("/a/docs/x"), Path("/a/docs")) and within(Path("/a/docs"), Path("/a/docs"))
    assert not within(Path("/a/docs_sibling"), Path("/a/docs")) and not within(Path("/a"), Path("/a/docs"))


async def test_nothing_is_indexed_until_a_folder_is_added(store, tmp_path):
    tree(tmp_path / "docs")
    index = FolderIndex(store)
    await index.run_all()
    assert index.list() == [] and store.stats()["memories"] == 0
    index.add(str(tmp_path / "docs"))
    assert store.stats()["memories"] == 0  # adding chooses the folder; a pass reads it


async def test_default_rules_take_text_markdown_code_and_html_and_skip_the_rest(store, tmp_path):
    index = FolderIndex(store)
    folder = index.add(str(tree(tmp_path / "docs")))
    assert folder.include == list(DEFAULT_INCLUDE) and folder.exclude == list(DEFAULT_EXCLUDE)
    job = await run(index, folder.id)
    base = Path(folder.path)
    assert sources(store) == {f"file:{(base / p).as_posix()}"
                              for p in ("notas/plan.md", "notas/ideas.txt", "src/app.py", "web/index.html")}
    assert (job.state, job.total, job.indexed) == ("done", 5, 4)  # raro.txt passes the rules, then proves binary
    assert job.skipped == {"venv": 1, "binary": 1}  # hidden, node_modules, secrets, build and .png never counted
    page = next(m for m in store.list(kind="document") if m.source.endswith("index.html"))
    assert "Portada" in page.text and "oculto" not in page.text  # the extractors' rules apply
    hits = store.search("cliente Norte 60 días", [GLOBAL])
    assert hits[0].memory.source == f"file:{(base / 'notas/plan.md').as_posix()}"  # the hit carries its path
    assert hits[0].memory.meta["folder"] == folder.id and hits[0].memory.meta["rel"] == "notas/plan.md"
    assert not store.search("ghp_hidden_token hidden-env paquete externo", [GLOBAL])


async def test_custom_include_and_exclude_globs_and_limits(store, tmp_path):
    root = write(tmp_path / "docs", {
        "a.md": "alfa unica", "B.MD": "beta unica", "b.draft.md": "borrador beta", "drafts/c.md": "gamma borrador",
        "d.txt": "delta unica", "e.md": "x" * 3000, "f.md": "foxtrot unica", "g.md": "golf unica"})
    index = FolderIndex(store)
    folder = index.add(str(root), include=["*.md"], exclude=["*.draft.md", "drafts/*"], max_file_bytes=2048,
                       max_files=3)
    job = await run(index, folder.id)
    assert {Path(s).name for s in sources(store)} == {"a.md", "B.MD", "f.md"}  # d.txt not included; e.md too big
    assert (job.indexed, job.skipped) == (3, {"too_big": 1, "limit": 1})  # the 4th file that fits is over the limit
    for bad in (dict(include=[]), dict(include="*.md"), dict(exclude=["x"] * 101), dict(max_files=0),
                dict(max_file_bytes=10), dict(max_files=True), dict(include=[None])):
        with pytest.raises(FolderError):
            index.update(folder.id, **bad)


async def test_pdf_and_word_files_use_the_existing_extractors_or_are_skipped(store, tmp_path):
    docx = pytest.importorskip("docx")
    root = tmp_path / "docs"
    root.mkdir()
    doc = docx.Document()
    doc.add_paragraph("Contrato con el proveedor Delta, penalización del 3 %")
    doc.save(root / "contrato.docx")
    write(root, {"roto.pdf": b"%PDF-1.4 not really a pdf"})
    index = FolderIndex(store)
    folder = index.add(str(root))
    job = await run(index, folder.id)
    assert any("proveedor Delta" in m.text for m in store.list(kind="document"))
    assert job.skipped == {"unreadable": 1}


async def test_only_changed_files_are_read_again(store, tmp_path, monkeypatch):
    root = write(tmp_path / "docs", {"a.md": "alfa originalalfa", "b.md": "beta originalbeta", "c.md": "gamma originalgamma"})
    read = []
    real = folders_module.extract_text
    monkeypatch.setattr(folders_module, "extract_text", lambda p: read.append(p.name) or real(p))
    index = FolderIndex(store)
    folder = index.add(str(root))
    first = await run(index, folder.id)
    assert (first.indexed, first.unchanged) == (3, 0) and sorted(read) == ["a.md", "b.md", "c.md"]
    ids = {Path(m.source).name: m.id for m in store.list(kind="document")}

    read.clear()
    again = await run(index, folder.id)
    assert (again.indexed, again.unchanged, again.removed) == (0, 3, 0) and read == []
    assert {Path(m.source).name: m.id for m in store.list(kind="document")} == ids  # nothing was replaced

    path = Path(folder.path) / "b.md"
    stamp = path.stat().st_mtime_ns
    path.write_text("beta nueva versión con más texto", encoding="utf-8")  # size changes
    (Path(folder.path) / "c.md").write_text("gamma originalgamma", encoding="utf-8")  # same text...
    os.utime(Path(folder.path) / "c.md", ns=(stamp + 10**9, stamp + 10**9))  # ...a later time
    (Path(folder.path) / "d.md").write_text("delta nuevo", encoding="utf-8")
    (Path(folder.path) / "a.md").unlink()
    read.clear()
    third = await run(index, folder.id)
    assert (third.indexed, third.unchanged, third.removed) == (3, 0, 1) and sorted(read) == ["b.md", "c.md", "d.md"]
    now = {Path(m.source).name: m.id for m in store.list(kind="document")}
    assert set(now) == {"b.md", "c.md", "d.md"} and now["b.md"] != ids["b.md"]
    assert store.search("beta nueva versión", [GLOBAL]) and not store.search("originalbeta", [GLOBAL])
    assert not store.search("originalalfa", [GLOBAL])  # the deleted file is forgotten

    read.clear()
    forced = await run(index, folder.id, force=True)
    assert (forced.indexed, forced.unchanged) == (3, 0) and len(read) == 3


async def test_a_file_that_cannot_be_read_is_not_tried_again_until_it_changes(store, tmp_path, monkeypatch):
    root = write(tmp_path / "docs", {"roto.pdf": b"%PDF-1.4 garbage", "ok.md": "texto bueno"})
    calls = []
    real = folders_module.extract_text
    monkeypatch.setattr(folders_module, "extract_text", lambda p: calls.append(p.name) or real(p))
    index = FolderIndex(store)
    folder = index.add(str(root))
    first = await run(index, folder.id)
    second = await run(index, folder.id)
    assert calls.count("roto.pdf") == 1 and first.skipped == second.skipped == {"unreadable": 1}
    assert second.unchanged == 2 and [f["status"] for f in index.files(folder.id)] == ["indexed", "unreadable"]


# ------------------------------------------------------------------------------------------- staying inside
def link(target: Path, path: Path, directory: bool = False) -> None:
    try:
        path.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")


async def test_nothing_outside_the_chosen_folder_is_read(store, tmp_path):
    docs = write(tmp_path / "docs", {"propio.md": "Texto propio del proyecto", "notas/ok.md": "otra nota propia"})
    write(tmp_path / "docs_sibling", {"secreto.md": f"credenciales del hermano {SECRET}"})
    write(tmp_path / "fuera", {"dentro.md": f"archivo de otra carpeta {SECRET}"})
    link(tmp_path / "docs_sibling" / "secreto.md", docs / "enlace.md")  # a link to a file outside
    link(tmp_path / "fuera", docs / "enlace_dir", directory=True)  # a link to a folder outside
    link(docs / "propio.md", docs / "alias.md")  # a link that stays inside is only a second name
    index = FolderIndex(store)
    folder = index.add(str(docs))
    job = await run(index, folder.id)
    assert job.state == "done" and not store.search(SECRET, [GLOBAL])
    assert {Path(s).name for s in sources(store)} == {"propio.md", "ok.md", "alias.md"}
    assert job.skipped == {"outside": 1, "link": 1}
    assert SECRET.encode() not in (tmp_path / "home" / "memory.db").read_bytes()


async def test_a_link_swapped_in_after_the_scan_is_not_followed(store, tmp_path):
    docs = write(tmp_path / "docs", {"nota.md": "texto inocente"})
    write(tmp_path / "otro", {"privado.md": f"privado {SECRET}"})
    index = FolderIndex(store)
    folder = index.add(str(docs))
    scan = folders_module.scan_folder(folder)
    (docs / "nota.md").unlink()
    link(tmp_path / "otro" / "privado.md", docs / "nota.md")  # the file became a link between scan and read
    assert index._index_file(folder, scan.files[0]) == "outside"
    assert not store.search(SECRET, [GLOBAL]) and store.stats()["memories"] == 0


async def test_spikes_own_data_folder_is_never_indexed(store, tmp_path):
    root = write(tmp_path / "all", {"mis/notas.md": "nota normal", "spike-home/secrets.json": f'{{"k": "{SECRET}"}}'})
    index = FolderIndex(store, protected=lambda: [root / "spike-home"])
    with pytest.raises(FolderError, match="own data"):
        index.add(str(root / "spike-home"))
    folder = index.add(str(root), include=["*"], exclude=[])  # a rule that would take everything
    job = await run(index, folder.id)
    assert {Path(s).name for s in sources(store)} == {"notas.md"} and job.skipped == {"outside": 1}
    assert not store.search(SECRET, [GLOBAL])


def test_folders_are_checked_when_added(store, tmp_path):
    root = write(tmp_path / "docs", {"a.md": "x", "sub/b.md": "y"})
    index = FolderIndex(store)
    for path, why in (("docs", "absolute"), (str(tmp_path / "nope"), "does not exist"),
                      (str(root / "a.md"), "not a folder"), (os.path.abspath(os.sep), "whole disk"),
                      ("", "choose a folder")):
        with pytest.raises(FolderError, match=why):
            index.add(path)
    index.add(str(root))
    for path in (str(root), str(root / "sub"), str(tmp_path)):  # itself, inside it, around it
        with pytest.raises(FolderError, match="overlaps"):
            index.add(path)
    write(tmp_path / "docs2", {"c.md": "z"})
    assert len(index.list()) == 1 and index.add(str(tmp_path / "docs2")) and len(index.list()) == 2


async def test_a_huge_folder_is_cut_with_a_warning(store, tmp_path, monkeypatch):
    root = write(tmp_path / "docs", {f"f{i:02}.md": f"nota {i}" for i in range(10)})
    monkeypatch.setattr(folders_module, "MAX_SCAN", 4)
    index = FolderIndex(store)
    job = await run(index, index.add(str(root)).id)
    assert job.state == "done" and job.total == 4 and "more than 4" in job.warning


# ------------------------------------------------------------------------------------------- forgetting
async def test_forgetting_a_folder_removes_chunks_words_and_vectors_from_the_file(store, tmp_path):
    service = MemoryService(store, lambda: _ret(ConceptEmbedder()))
    keep = store.add("Dato que se queda", "fact")
    write(tmp_path / "uno", {"cuenta.md": f"Mi contraseña del banco es {SECRET} y el coche está en el garaje",
                             "larga.txt": "\n\n".join(f"Párrafo {i}. " + "palabra " * 60 for i in range(12))})
    write(tmp_path / "dos", {"otra.md": "La factura del perro vence el día 5"})
    one = service.folders.add(str(tmp_path / "uno"))
    two = service.folders.add(str(tmp_path / "dos"))
    job = await run(service.folders, one.id)
    await run(service.folders, two.id)
    assert job.embedded > 0 and store.search(SECRET, [GLOBAL])
    db = store._db
    mine = "(SELECT memory_id FROM folder_files WHERE folder_id = ?)"
    chunks = db.execute(f"SELECT COUNT(*) FROM chunks WHERE memory_id IN {mine}", (one.id,)).fetchone()[0]
    assert chunks >= 2 and db.execute(f"SELECT COUNT(embedding) FROM chunks WHERE memory_id IN {mine}",
                                      (one.id,)).fetchone()[0] == chunks

    gone = service.folders.forget(one.id)
    assert gone == {"files": 2, "chunks": chunks} and service.folders.forget(one.id) is None
    assert not store.search(SECRET, [GLOBAL]) and not store.search("palabra Párrafo", [GLOBAL])
    assert db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (SECRET,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM folder_files WHERE folder_id = ?", (one.id,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM folders WHERE id = ?", (one.id,)).fetchone()[0] == 0
    remaining = db.execute("SELECT COUNT(*), COUNT(embedding) FROM chunks").fetchone()
    assert remaining[0] == remaining[1] == store.stats()["chunks"] == 2  # the other folder's file and the note
    raw = (tmp_path / "home" / "memory.db").read_bytes()
    assert SECRET.encode() not in raw and b"cuenta.md" not in raw and b"garaje" not in raw
    assert store.get(keep.id) is not None and store.search("factura del perro", [GLOBAL])
    assert [f.id for f in service.folders.list()] == [two.id]


async def test_forgetting_a_folder_while_it_is_being_indexed_leaves_nothing(store, tmp_path, monkeypatch):
    root = write(tmp_path / "docs", {f"n{i}.md": f"nota {i} {SECRET}" for i in range(4)})
    index = FolderIndex(store)
    folder = index.add(str(root))
    original = index._index_file
    seen = []

    def forget_after_the_first(f, cand):
        status = original(f, cand)
        if not seen:
            seen.append(cand.rel)
            index.forget(f.id)
        return status

    monkeypatch.setattr(index, "_index_file", forget_after_the_first)
    job = await run(index, folder.id)
    assert job.state == "cancelled" and store.stats()["memories"] == 0 and index.list() == []
    assert SECRET.encode() not in (tmp_path / "home" / "memory.db").read_bytes()


# ------------------------------------------------------------------------------------------- vectors
async def test_new_chunks_get_vectors_and_a_broken_embedder_only_warns(store, tmp_path):
    service = MemoryService(store, lambda: _ret(ConceptEmbedder()))
    folder = service.folders.add(str(write(tmp_path / "docs", {"a.md": "mi coche rojo", "b.md": "el perro Toby"})))
    job = await run(service.folders, folder.id)
    assert job.embedded == 2 and store.stats()["embedded"] == 2
    found = await service.recall("¿qué automóvil tengo?", None)
    assert found.hits and found.hits[0].memory.source.endswith("a.md")

    class Broken(ConceptEmbedder):
        async def embed(self, texts, query=False):
            raise OSError("embedding server is down")

    broken = MemoryService(store, lambda: _ret(Broken()))
    write(tmp_path / "docs", {"c.md": "una nota nueva"})
    job2 = await run(broken.folders, folder.id)
    assert job2.state == "done" and "vectors pending" in job2.warning and store.search("nota nueva", [GLOBAL])


# ------------------------------------------------------------------------------------------- the API
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path / "home", provider_factory=factory)
    state.memory.get_embedder = no_embedder
    with TestClient(create_app(state), client=LOCAL) as client:
        yield client, state, local


def wait_for(client, folder_id, states=("done", "error", "cancelled")):
    for _ in range(300):
        folder = client.get(f"/api/memory-folders/{folder_id}").json()
        if folder["job"] and folder["job"]["state"] in states:
            return folder
        time.sleep(0.02)
    raise AssertionError(f"the pass did not finish: {folder['job']}")


def test_folder_api_indexes_in_the_background_and_shows_progress(api, tmp_path, monkeypatch):
    client, state, _ = api
    root = write(tmp_path / "docs", {f"n{i}.md": f"nota número {i} sobre el tema {i}" for i in range(3)})
    first_file_read, release = threading.Event(), threading.Event()
    original = FolderIndex._index_file

    def slow(self, folder, cand):
        first_file_read.set()
        release.wait(5)
        return original(self, folder, cand)

    monkeypatch.setattr(FolderIndex, "_index_file", slow)
    listed = client.get("/api/memory-folders").json()
    assert listed["folders"] == [] and "*.md" in listed["defaults"]["include"]
    assert client.get("/api/memory-status").json()["stats"]["memories"] == 0
    added = client.post("/api/memory-folders", json={"path": str(root)})
    assert added.status_code == 200
    fid = added.json()["id"]
    assert first_file_read.wait(5)
    midway = client.get(f"/api/memory-folders/{fid}").json()
    assert midway["job"]["state"] == "indexing" and midway["job"]["total"] == 3 and midway["job"]["done"] == 0
    assert midway["job"]["current"] == "n0.md" and midway["files"] == 0
    release.set()
    done = wait_for(client, fid)
    assert done["job"]["state"] == "done" and done["files"] == 3 and done["chunks"] == 3
    assert done["job"]["indexed"] == 3 and done["indexed"] is not None
    assert [f["path"] for f in client.get(f"/api/memory-folders/{fid}/files").json()] == ["n0.md", "n1.md", "n2.md"]
    assert len(client.get("/api/memory?kind=document").json()) == 3
    assert client.get("/api/memory-folders/nope").status_code == 404

    # on demand: nothing changed, so nothing is read again; a force reads everything
    monkeypatch.setattr(FolderIndex, "_index_file", original)
    client.post(f"/api/memory-folders/{fid}/reindex", json={})
    assert wait_for(client, fid)["job"]["unchanged"] == 3
    client.post(f"/api/memory-folders/{fid}/reindex", json={"force": True})
    assert wait_for(client, fid)["job"]["indexed"] == 3


def test_rules_can_be_changed_and_the_folder_forgotten(api, tmp_path):
    client, state, _ = api
    root = write(tmp_path / "docs", {"a.md": "alfa única", "b.txt": "beta única"})
    fid = client.post("/api/memory-folders", json={"path": str(root)}).json()["id"]
    assert wait_for(client, fid)["files"] == 2
    patched = client.patch(f"/api/memory-folders/{fid}", json={"include": ["*.md"]})
    assert patched.json()["include"] == ["*.md"]
    done = wait_for(client, fid)
    assert done["files"] == 1 and done["job"]["removed"] == 1 and not state.memory.store.search("beta", ["global"])
    assert client.patch(f"/api/memory-folders/{fid}", json={"max_files": 0}).status_code == 400
    assert client.patch("/api/memory-folders/nope", json={}).status_code == 404
    gone = client.delete(f"/api/memory-folders/{fid}")
    assert gone.json() == {"ok": True, "files": 1, "chunks": 1}
    assert client.get("/api/memory-folders").json()["folders"] == [] and state.memory.store.stats()["memories"] == 0
    assert client.delete(f"/api/memory-folders/{fid}").status_code == 404


def test_choosing_folders_needs_this_computer_and_a_valid_folder(api, tmp_path):
    client, state, _ = api
    root = write(tmp_path / "docs", {"a.md": "texto"})
    elsewhere = TestClient(client.app)  # not 127.0.0.1: another machine on the network
    assert elsewhere.post("/api/memory-folders", json={"path": str(root)}).status_code == 403
    assert state.memory.folders.list() == []
    for body, why in (({"path": "relativa"}, "absolute"), ({"path": str(tmp_path / "no")}, "does not exist"),
                      ({"path": str(root), "scope": "project:nope"}, "scope"),
                      ({"path": str(root), "max_files": 10**9}, "limit")):
        r = client.post("/api/memory-folders", json=body)
        assert r.status_code == 400 and why in r.json()["detail"], body
    fid = client.post("/api/memory-folders", json={"path": str(root)}).json()["id"]
    assert client.post("/api/memory-folders", json={"path": str(root)}).status_code == 400  # already there
    assert elsewhere.patch(f"/api/memory-folders/{fid}", json={"include": ["*"]}).status_code == 403
    assert elsewhere.delete(f"/api/memory-folders/{fid}").status_code == 200  # forgetting never widens access


def test_answers_cite_the_file_path_and_keep_it_private(api, tmp_path):
    client, state, local = api
    root = write(tmp_path / "docs", {"notas/plan.md": "El cliente Norte paga a 60 días", "otro.md": "El perro Toby"})
    fid = client.post("/api/memory-folders", json={"path": str(root)}).json()["id"]
    wait_for(client, fid)
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "¿A cuántos días paga el cliente Norte?"})
    system = local.requests[-1].messages[0]
    cited = f"file {(Path(state.memory.folders.get(fid).path) / 'notas/plan.md').as_posix()}"
    assert f"[{cited} ·" in system.content and "paga a 60 días" in system.content and "Toby" not in system.content
    assert any("paga a 60 días" in p for p in system.private)  # files are withheld from remote providers
    hits = state.memory.store.search("cliente Norte", ["global"])
    assert memory_section(type("R", (), {"rules": [], "hits": hits, "saved": [], "glossary": [], "due": []})(),
                          500)[1]


def test_a_project_folder_is_seen_only_in_that_project_and_dies_with_it(api, tmp_path):
    client, state, local = api
    root = write(tmp_path / "docs", {"plan.md": "El presupuesto de Atlas es de 40 mil euros"})
    pid = client.post("/api/projects", json={"name": "Atlas"}).json()["id"]
    fid = client.post("/api/memory-folders", json={"path": str(root), "scope": f"project:{pid}"}).json()["id"]
    wait_for(client, fid)
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "¿Cuál es el presupuesto de Atlas?"})
    assert "40 mil" not in local.requests[-1].messages[0].content
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "¿Cuál es el presupuesto de Atlas?", "project_id": pid})
    assert "40 mil" in local.requests[-1].messages[0].content
    client.delete(f"/api/projects/{pid}")
    assert state.memory.folders.list() == [] and state.memory.store.stats()["memories"] == 0


def test_clearing_memory_also_forgets_the_folders(api, tmp_path):
    client, state, _ = api
    root = write(tmp_path / "docs", {"a.md": "algo"})
    fid = client.post("/api/memory-folders", json={"path": str(root)}).json()["id"]
    wait_for(client, fid)
    client.post("/api/memory", json={"text": "una nota", "kind": "fact"})
    assert client.delete("/api/memory?scope=all").json()["deleted"] == 1  # the note; the file went with its folder
    assert state.memory.store.stats()["memories"] == 0
    assert client.get("/api/memory-folders").json()["folders"] == []  # or the next start would index it again


def test_on_start_only_changed_files_are_read_again(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    root = write(tmp_path / "docs", {"a.md": "alfa original", "b.md": "beta original", "c.md": "gamma original"})
    state = AppState(home=tmp_path / "home")
    state.memory.get_embedder = no_embedder
    with TestClient(create_app(state), client=LOCAL) as client:
        fid = client.post("/api/memory-folders", json={"path": str(root)}).json()["id"]
        assert wait_for(client, fid)["job"]["indexed"] == 3
    # SPIKE is closed; the files change meanwhile
    (Path(state.memory.folders.get(fid).path) / "b.md").write_text("beta cambiada del todo", encoding="utf-8")
    (Path(state.memory.folders.get(fid).path) / "d.md").write_text("delta nueva", encoding="utf-8")
    read = []
    real = folders_module.extract_text
    monkeypatch.setattr(folders_module, "extract_text", lambda p: read.append(p.name) or real(p))
    again = AppState(home=tmp_path / "home")
    again.memory.get_embedder = no_embedder
    with TestClient(create_app(again), client=LOCAL) as client:
        job = wait_for(client, fid)["job"]
        assert (job["indexed"], job["unchanged"], job["removed"]) == (2, 2, 0) and sorted(read) == ["b.md", "d.md"]


def test_nothing_runs_on_start_when_memory_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    root = write(tmp_path / "docs", {"a.md": "alfa"})
    state = AppState(home=tmp_path / "home")
    state.memory.get_embedder = no_embedder
    state.memory.folders.add(str(root))
    state.update_settings({"memory": {"enabled": False, "embeddings": "auto", "auto_summary": True}})
    with TestClient(create_app(state), client=LOCAL) as client:
        time.sleep(0.2)
        assert state.memory.store.stats()["memories"] == 0
        assert client.get("/api/memory-folders").json()["folders"][0]["job"] is None
