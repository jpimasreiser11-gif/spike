"""G21: every Hugging Face source can pin a `revision` (commit hash); no revision means the old behaviour. No network."""

import hashlib
import sys
import types
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "evals"))

import prepare  # noqa: E402
import run_eval  # noqa: E402
import yaml  # noqa: E402
from spike_train import licenses, sources  # noqa: E402

from spike.runtime import models  # noqa: E402

REV = "a" * 40
SRC = {"hub": "openai/gsm8k", "config": "main", "split": "train", "license": "mit", "role": "train", "format": "gsm8k"}


def fake_datasets(monkeypatch, calls):
    def load_dataset(repo, config=None, split=None, streaming=False, **kw):
        calls.append({"repo": repo, "config": config, "split": split, **kw})
        return iter([{"question": "2+2?", "answer": "Four.\n#### 4"}])
    monkeypatch.setitem(sys.modules, "datasets", types.SimpleNamespace(load_dataset=load_dataset))


# ------------------------------------------------------------------ datasets (hub:)
def test_hub_source_without_revision_calls_the_loader_exactly_as_before(monkeypatch):
    calls = []
    fake_datasets(monkeypatch, calls)
    assert len(list(prepare.load_rows(SRC))) == 1
    assert calls == [{"repo": "openai/gsm8k", "config": "main", "split": "train"}]  # no `revision` key at all
    assert sources.origin(SRC) == {"hub": "openai/gsm8k"}


def test_prepare_passes_the_pinned_revision_to_the_loader_and_records_it(monkeypatch):
    calls = []
    fake_datasets(monkeypatch, calls)
    pinned = {**SRC, "revision": REV}
    assert len(list(prepare.load_rows(pinned))) == 1
    assert calls[0]["revision"] == REV
    assert sources.origin(pinned) == {"hub": "openai/gsm8k", "revision": REV}


def test_verify_sources_and_distill_stream_the_pinned_revision_too(monkeypatch):
    import distill
    import verify_sources
    calls = []
    fake_datasets(monkeypatch, calls)
    list(verify_sources.stream_rows(SRC))
    list(verify_sources.stream_rows({**SRC, "revision": REV}))
    distill.gold_tasks({"source": "g", "max": 1}, {"g": {**SRC, "revision": REV}}, "system")
    assert "revision" not in calls[0] and calls[1]["revision"] == REV and calls[2]["revision"] == REV


def test_a_revision_must_be_a_full_commit_hash(monkeypatch):
    for bad in ("main", "abc123", "A" * 40, ""):
        with pytest.raises(ValueError, match="revision"):
            sources.hub_revision({**SRC, "revision": bad})
    assert sources.hub_revision(SRC) is None and sources.hub_revision({**SRC, "revision": REV}) == REV
    fake_datasets(monkeypatch, [])
    with pytest.raises(ValueError, match="revision"):
        list(prepare.load_rows({**SRC, "revision": "main"}))


def test_the_license_gate_reads_the_pinned_revision_from_the_hub(monkeypatch):
    seen = []
    monkeypatch.setattr(licenses, "_hub_license",
                        lambda kind, repo, revision=None: seen.append((kind, repo, revision)) or "mit")
    assert licenses.source_license({**SRC, "revision": REV}) == "mit"
    assert licenses.source_license(SRC) == "mit"
    assert seen == [("datasets", "openai/gsm8k", REV), ("datasets", "openai/gsm8k", None)]


def test_license_request_url_uses_the_revision_endpoint_only_when_pinned(monkeypatch):
    urls = []

    def get(url, timeout=None):
        urls.append(url)
        return httpx.Response(200, json={"cardData": {"license": "mit"}}, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", get)
    licenses.hub_license("openai/gsm8k")
    licenses.hub_license("openai/gsm8k", REV)
    assert urls == ["https://huggingface.co/api/datasets/openai/gsm8k",
                    f"https://huggingface.co/api/datasets/openai/gsm8k/revision/{REV}"]


def test_origin_of_registry_sources():
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    assert "revision" not in sources.origin(registry["gsm8k-train"])  # default: nothing pinned, nothing recorded
    assert sources.origin({**registry["gsm8k-train"], "revision": REV})["revision"] == REV
    assert sources.origin(registry["finqa-test"])["revision"] == registry["finqa-test"]["revision"]  # URL sources, as before


def test_the_data_manifest_of_prepare_main_records_the_revision(monkeypatch, tmp_path):
    """The same `origin(src)` that prepare.main writes into manifest.json for each source it uses."""
    import inspect
    assert "**origin(src)" in inspect.getsource(prepare.main)


# ------------------------------------------------------------------ evals
def test_run_eval_passes_the_pinned_revision_to_the_loader(monkeypatch):
    calls = []
    fake_datasets(monkeypatch, calls)
    monkeypatch.setattr(licenses, "hub_license", lambda repo, revision=None: "mit")
    task = {"name": "gsm8k", "source": "gsm8k"}
    ev_src = {**SRC, "role": "eval", "split": "test"}
    run_eval.load_items(task, {"gsm8k": ev_src}, 0, None)
    run_eval.load_items(task, {"gsm8k": {**ev_src, "revision": REV}}, 0, None)
    assert "revision" not in calls[0] and calls[1]["revision"] == REV


def test_eval_summary_meta_lists_the_revision_of_each_source():
    reg = {"gsm8k": {**SRC, "role": "eval", "revision": REV},
           "mmlu-pro": {"hub": "TIGER-Lab/MMLU-Pro", "split": "test", "role": "eval"},
           "finqa-test": {"urls": [], "revision": "b" * 40, "repo": "https://github.com/czyssrs/FinQA"},
           "mine": {"file": "evals/data/science_eval.jsonl"}}
    suites = {"s": {"tasks": [{"name": "t1", "source": "gsm8k"}, {"name": "t2", "source": "mmlu-pro"},
                              {"name": "t3", "source": "finqa-test"}, {"name": "t4", "source": "mine"},
                              {"name": "t5"}, {"name": "t6", "source": "gsm8k"}]}}
    assert run_eval.source_revisions(["s"], suites, reg) == {
        "gsm8k": REV, "mmlu-pro": None, "finqa-test": "b" * 40, "mine": None}


def test_eval_markdown_names_pinned_and_unpinned_sources():
    meta = {"run_id": "r", "model": "m.gguf", "max_tokens": 1, "host": "h",
            "source_revisions": {"gsm8k": REV, "mmlu-pro": None}}
    md = run_eval.render_markdown({"meta": meta, "tasks": {}, "suites": {}})
    assert f"`gsm8k` @ `{REV[:12]}`" in md and "`mmlu-pro` (not pinned)" in md
    bare = run_eval.render_markdown({"meta": {**meta, "source_revisions": {}}, "tasks": {}, "suites": {}})
    assert "Data revisions" not in bare


# ------------------------------------------------------------------ model downloads
def hub(requests, body=b"weights"):
    digest = hashlib.sha256(body).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        path = request.url.path
        if "/tree/" in path:
            return httpx.Response(200, json=[{"path": "Qwen3.5-2B-Q4_K_M.gguf", "size": len(body),
                                              "lfs": {"oid": digest, "size": len(body)}}])
        if path.startswith("/api/models/"):
            return httpx.Response(200, json={"cardData": {"license": "apache-2.0"}})
        return httpx.Response(200, content=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_model_download_without_revision_keeps_using_main(tmp_path):
    requests = []
    path, _ = await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub(requests))
    assert requests == ["/api/models/unsloth/Qwen3.5-2B-GGUF", "/api/models/unsloth/Qwen3.5-2B-GGUF/tree/main",
                        "/unsloth/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-Q4_K_M.gguf"]
    assert models.model_manifest(path)["revision"] is None


async def test_model_download_pins_listing_and_file_to_the_revision_and_records_it(tmp_path):
    requests = []
    path, verified = await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub(requests), revision=REV)
    assert verified
    assert requests == [f"/api/models/unsloth/Qwen3.5-2B-GGUF/revision/{REV}",
                        f"/api/models/unsloth/Qwen3.5-2B-GGUF/tree/{REV}",
                        f"/unsloth/Qwen3.5-2B-GGUF/resolve/{REV}/Qwen3.5-2B-Q4_K_M.gguf"]
    assert models.model_manifest(path)["revision"] == REV


async def test_a_catalogue_entry_can_carry_its_own_revision(tmp_path, monkeypatch):
    entry = models.MODELS["qwen3.5-2b"]
    monkeypatch.setitem(models.MODELS, "qwen3.5-2b", models.ModelEntry(**{**entry.__dict__, "revision": REV}))
    requests = []
    path, _ = await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub(requests))
    assert requests[-1].startswith(f"/unsloth/Qwen3.5-2B-GGUF/resolve/{REV}/")
    assert models.model_manifest(path)["revision"] == REV


async def test_a_bad_model_revision_is_refused_before_any_request(tmp_path):
    requests = []
    with pytest.raises(ValueError, match="revision"):
        await models.download("qwen3.5-2b", dest_dir=tmp_path, client=hub(requests), revision="main")
    assert requests == []


def test_cli_pull_passes_the_revision(monkeypatch, tmp_path):
    from spike import cli
    seen = {}

    async def fake_download(model, quant=None, **kw):
        seen.update(kw)
        return tmp_path / "x.gguf", True
    monkeypatch.setattr(models, "download", fake_download)
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    cli.main(["models", "pull", "qwen3.5-2b", "--revision", REV])
    assert seen["revision"] == REV
