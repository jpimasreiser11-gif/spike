"""Create a tiny random-weight GGUF model and LoRA adapters for integration tests.

The model produces meaningless text. It exists only to exercise the real llama-server process: startup,
health, streaming, chat templates, and per-request LoRA switching. Never use it to judge quality.

    python tests/fixtures/make_tiny_gguf.py OUT_DIR
"""

from __future__ import annotations

import sys
from pathlib import Path

import gguf
import numpy as np

N_EMBD, N_LAYER, N_HEAD, N_HEAD_KV, N_FF, CTX = 64, 2, 4, 2, 128, 2048
CHAT_TEMPLATE = (
    "{% for m in messages %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endfor %}"
    "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}"
)


def vocab() -> tuple[list[bytes], list[float], list[int]]:
    tokens = [b"<unk>", b"<s>", b"</s>", b"<|im_start|>", b"<|im_end|>"]
    types = [gguf.TokenType.UNKNOWN, gguf.TokenType.CONTROL, gguf.TokenType.CONTROL, gguf.TokenType.CONTROL,
             gguf.TokenType.CONTROL]
    for b in range(256):
        tokens.append(f"<0x{b:02X}>".encode())
        types.append(gguf.TokenType.BYTE)
    for word in ["▁the", "▁a", "▁and", "▁of", "▁to", "▁SPIKE", "▁hello", "▁world"]:
        tokens.append(word.encode())
        types.append(gguf.TokenType.NORMAL)
    scores = [0.0] * len(tokens)
    return tokens, scores, [int(t) for t in types]


def write_model(path: Path, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    tokens, scores, types = vocab()
    n_vocab = len(tokens)
    w = gguf.GGUFWriter(str(path), "llama")
    w.add_name("spike-tiny-test")
    w.add_context_length(CTX)
    w.add_embedding_length(N_EMBD)
    w.add_block_count(N_LAYER)
    w.add_feed_forward_length(N_FF)
    w.add_head_count(N_HEAD)
    w.add_head_count_kv(N_HEAD_KV)
    w.add_rope_dimension_count(N_EMBD // N_HEAD)
    w.add_layer_norm_rms_eps(1e-5)
    w.add_file_type(gguf.LlamaFileType.ALL_F32)
    w.add_tokenizer_model("llama")
    w.add_token_list(tokens)
    w.add_token_scores(scores)
    w.add_token_types(types)
    w.add_bos_token_id(1)
    w.add_eos_token_id(4)  # <|im_end|> ends a turn
    w.add_unk_token_id(0)
    w.add_add_bos_token(False)
    w.add_chat_template(CHAT_TEMPLATE)

    def t(name: str, *shape: int) -> None:
        w.add_tensor(name, (rng.standard_normal(shape) * 0.02).astype(np.float32))

    t("token_embd.weight", n_vocab, N_EMBD)
    w.add_tensor("output_norm.weight", np.ones(N_EMBD, dtype=np.float32))
    t("output.weight", n_vocab, N_EMBD)
    head_dim = N_EMBD // N_HEAD
    for i in range(N_LAYER):
        w.add_tensor(f"blk.{i}.attn_norm.weight", np.ones(N_EMBD, dtype=np.float32))
        t(f"blk.{i}.attn_q.weight", N_EMBD, N_EMBD)
        t(f"blk.{i}.attn_k.weight", N_HEAD_KV * head_dim, N_EMBD)
        t(f"blk.{i}.attn_v.weight", N_HEAD_KV * head_dim, N_EMBD)
        t(f"blk.{i}.attn_output.weight", N_EMBD, N_EMBD)
        w.add_tensor(f"blk.{i}.ffn_norm.weight", np.ones(N_EMBD, dtype=np.float32))
        t(f"blk.{i}.ffn_gate.weight", N_FF, N_EMBD)
        t(f"blk.{i}.ffn_up.weight", N_FF, N_EMBD)
        t(f"blk.{i}.ffn_down.weight", N_EMBD, N_FF)
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()


def write_lora(path: Path, seed: int, rank: int = 4, alpha: float = 8.0) -> None:
    rng = np.random.default_rng(seed)
    w = gguf.GGUFWriter(str(path), "llama")
    w.add_string(gguf.Keys.General.TYPE, gguf.GGUFType.ADAPTER)
    w.add_string(gguf.Keys.Adapter.TYPE, "lora")
    w.add_float32(gguf.Keys.Adapter.LORA_ALPHA, alpha)
    for i in range(N_LAYER):
        for name, out_dim in (("attn_q", N_EMBD), ("attn_output", N_EMBD)):
            w.add_tensor(f"blk.{i}.{name}.weight.lora_a", (rng.standard_normal((rank, N_EMBD)) * 0.5).astype(np.float32))
            w.add_tensor(f"blk.{i}.{name}.weight.lora_b", (rng.standard_normal((out_dim, rank)) * 0.5).astype(np.float32))
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_model(out / "spike-tiny.gguf")
    write_lora(out / "spike-finance.gguf", seed=1)
    write_lora(out / "spike-medicine.gguf", seed=2)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/out")
