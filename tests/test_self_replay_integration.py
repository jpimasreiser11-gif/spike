"""The self-replay server check against a real llama-server process and the tiny random-weight GGUF model.

It verifies what the fake server in test_self_replay.py only imitates: llama-server's own GET /lora-adapters and
/props answers, and the completion fields the generator reads. The model's text is meaningless and is not checked.
Skipped automatically when llama-server is not installed; set SPIKE_LLAMA_SERVER to the binary to run it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from spike.runtime.llamacpp_server import LlamaServer, ServerConfig, find_binary

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

from spike_train.distill import Teacher  # noqa: E402
from spike_train.self_replay import check_server  # noqa: E402

BINARY = find_binary()
pytestmark = pytest.mark.skipif(BINARY is None, reason="llama-server not installed")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("tiny")
    subprocess.run([sys.executable, "tests/fixtures/make_tiny_gguf.py", str(out)], check=True, capture_output=True)
    return out


async def test_the_base_model_check_on_a_real_llama_server(tiny, tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    server = LlamaServer(ServerConfig(model=tiny / "spike-tiny.gguf", adapters=[tiny / "spike-finance.gguf"], port=8795,
                                      context=1024, kv_cache_type="f16", binary=BINARY))
    await server.start(timeout_s=60)
    teacher = Teacher(server.base_url + "/v1", "tiny")
    try:
        # the adapter is loaded but switched off (SPIKE's own server start): requests run the base model
        info = await check_server(teacher)
        assert info["adapters_checked"] is True and "build" in info
        # llama-server's own default for --lora is scale 1.0: the check must refuse it
        (await teacher.client.post(server.base_url + "/lora-adapters", json=[{"id": 0, "scale": 1.0}])).raise_for_status()
        with pytest.raises(ValueError, match="LoRA adapters applied"):
            await check_server(teacher)
        done = await teacher.complete([{"role": "user", "content": "hello SPIKE"}], temperature=0.0, max_tokens=4,
                                      thinking=False)
        assert done["finish_reason"] in ("stop", "length") and isinstance(done["completion_tokens"], int)
    finally:
        await teacher.aclose()
        await server.stop()
