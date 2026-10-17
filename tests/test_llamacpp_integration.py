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


async def test_server_lifecycle_streaming_and_adapter_isolation(tiny, tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    server = LlamaServer(ServerConfig(
        model=tiny / "spike-tiny.gguf",
        adapters=[tiny / "spike-finance.gguf", tiny / "spike-medicine.gguf"],
        port=8791, context=1024, kv_cache_type="f16", binary=BINARY,
    ))
    await server.start(timeout_s=60)
    try:
        assert server.status()["running"] and server.status()["rss_mb"] > 0
        provider = LlamaCppProvider(ProviderConfig(id="local", kind="llamacpp", name="local",
                                                   base_url=server.base_url + "/v1", local=True))
        assert set(await provider.adapters()) == {"spike-finance", "spike-medicine"}

        async def answer(adapter):
            req = ChatRequest(messages=[Message(role="user", content="hello SPIKE")], adapter=adapter,
                              temperature=0.0, max_tokens=12)
            events = [e async for e in provider.stream(req)]
            assert events[-1].kind == "done", events
            return "".join(e.text for e in events if e.kind == "text")

        base_1 = await answer(None)
        base_2 = await answer(None)  # cache hit path
        finance = await answer("spike-finance")
        base_3 = await answer(None)  # must not reuse KV computed with the adapter
        medicine = await answer("spike-medicine")
        assert base_1 == base_2 == base_3
        assert finance != base_1 and medicine != finance
        await provider.aclose()
    finally:
        await server.stop()
    assert not server.running()
