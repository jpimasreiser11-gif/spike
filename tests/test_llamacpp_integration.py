"""Integration tests against a real llama-server process and a tiny random-weight GGUF model.

They verify process lifecycle, streaming through SPIKE's provider, per-request adapter switching and the
prompt-cache isolation fix. Skipped automatically when llama-server is not installed.
Set SPIKE_LLAMA_SERVER to the binary to run them.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from spike.core.types import ChatRequest, Message
from spike.providers.base import ProviderConfig
from spike.providers.llamacpp import LlamaCppProvider
from spike.runtime.gguf import kv_cache_bytes, read_gguf
from spike.runtime.llamacpp_server import LlamaServer, ServerConfig, find_binary

BINARY = find_binary()
pytestmark = pytest.mark.skipif(BINARY is None, reason="llama-server not installed")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("tiny")
    subprocess.run([sys.executable, "tests/fixtures/make_tiny_gguf.py", str(out)], check=True, capture_output=True)
    return out


def test_gguf_reader_on_real_file(tiny):
    info = read_gguf(tiny / "spike-tiny.gguf")
    assert info.arch == "llama" and info.field("block_count") == 2
    # 2 layers * 2 kv heads * (16 + 16) dims * 2 bytes = 256 bytes/token
    assert kv_cache_bytes(info, 1000, "f16") == 256_000


async def _greedy(base_url: str, prompt: str, lora: list | None, cache: bool = False) -> list[int]:
    import httpx

    body = {"prompt": prompt, "n_predict": 12, "temperature": 0.0, "cache_prompt": cache, "return_tokens": True,
            "id_slot": 0}
    if lora is not None:
        body["lora"] = lora
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(base_url + "/completion", json=body)
    r.raise_for_status()
    return r.json()["tokens"]


VARIANTS = (("base", []), ("spike-finance", ["spike-finance"]), ("spike-medicine", ["spike-medicine"]))


def _provider(server: LlamaServer) -> LlamaCppProvider:
    return LlamaCppProvider(ProviderConfig(id="local", kind="llamacpp", name="local",
                                           base_url=server.base_url + "/v1", local=True))


async def _answer(provider: LlamaCppProvider, adapter: str | None) -> str:
    req = ChatRequest(messages=[Message(role="user", content="hello SPIKE")], adapter=adapter,
                      temperature=0.0, max_tokens=12)
    events = [e async for e in provider.stream(req)]
    assert events[-1].kind == "done", events
    return "".join(e.text for e in events if e.kind == "text")


async def _ground_truth(tiny: Path, port: int, prompt: str) -> tuple[dict[str, list[int]], dict[str, str]]:
    """Each variant on its own fresh server (base alone, or one adapter as the only one loaded), first request."""
    tokens, texts = {}, {}
    for name, adapters in VARIANTS:
        server = LlamaServer(ServerConfig(model=tiny / "spike-tiny.gguf", adapters=[tiny / f"{a}.gguf" for a in adapters],
                                          port=port, context=1024, kv_cache_type="f16", binary=BINARY))
        await server.start(timeout_s=60)
        try:
            tokens[name] = await _greedy(server.base_url, prompt, [{"id": 0, "scale": 1.0}] if adapters else None)
            provider = _provider(server)
            texts[name] = await _answer(provider, adapters[0] if adapters else None)
            await provider.aclose()
        finally:
            await server.stop()
    assert len({tuple(v) for v in tokens.values()}) == 3, "fixture adapters must change the output"
    assert len(set(texts.values())) == 3, "fixture adapters must change the output"
    return tokens, texts


async def test_server_lifecycle_streaming_and_adapter_isolation(tiny, tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    prompt = "<|im_start|>user\nhello SPIKE<|im_end|>\n<|im_start|>assistant\n"
    truth, expected = await _ground_truth(tiny, 8792, prompt)
    server = LlamaServer(ServerConfig(
        model=tiny / "spike-tiny.gguf",
        adapters=[tiny / "spike-finance.gguf", tiny / "spike-medicine.gguf"],
        port=8791, context=1024, kv_cache_type="f16", binary=BINARY,
    ))
    await server.start(timeout_s=60)
    try:
        assert server.status()["running"] and server.status()["rss_mb"] > 0
        # a client that sends no `lora` field gets the plain base model (global scales reset at startup)
        assert await _greedy(server.base_url, prompt, None) == truth["base"]

        provider = _provider(server)
        assert set(await provider.adapters()) == {"spike-finance", "spike-medicine"}
        # interleaved: cache hits and adapter switches in both directions
        for adapter in [None, None, "spike-finance", None, "spike-medicine", "spike-finance", "spike-finance", None]:
            assert await _answer(provider, adapter) == expected[adapter or "base"], adapter
        await provider.aclose()

        # server behaviour SPIKE relies on, with prompt caching forced on and explicit scales
        explicit = {"base": [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 0.0}],
                    "spike-finance": [{"id": 0, "scale": 1.0}, {"id": 1, "scale": 0.0}],
                    "spike-medicine": [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 1.0}]}
        for name in ["base", "spike-finance", "base", "spike-medicine", "spike-finance", "base"]:
            assert await _greedy(server.base_url, prompt, explicit[name], cache=True) == truth[name], name
    finally:
        await server.stop()
    assert not server.running()


async def test_empty_lora_list_is_not_the_base_model(tiny, tmp_path, monkeypatch):
    """Documents the llama-server behaviour behind SPIKE's explicit scales: `lora: []` uses global scales."""
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    prompt = "hello SPIKE the world"
    truth, _ = await _ground_truth(tiny, 8794, prompt)
    import httpx

    server = LlamaServer(ServerConfig(model=tiny / "spike-tiny.gguf", adapters=[tiny / "spike-finance.gguf"],
                                      port=8793, context=1024, kv_cache_type="f16", binary=BINARY))
    await server.start(timeout_s=60)
    try:
        async with httpx.AsyncClient() as client:  # restore llama-server's own default (scale 1.0)
            await client.post(server.base_url + "/lora-adapters", json=[{"id": 0, "scale": 1.0}])
        assert await _greedy(server.base_url, prompt, []) == truth["spike-finance"]
        assert await _greedy(server.base_url, prompt, [{"id": 0, "scale": 0.0}]) == truth["base"]
    finally:
        await server.stop()
