"""Chunked gated delta rule (training path for Qwen3.5 linear attention) against mlx-lm's sequential reference."""

import sys
from pathlib import Path

import pytest

mx = pytest.importorskip("mlx.core")
gd = pytest.importorskip("mlx_lm.models.gated_delta")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

from spike_train.gated_delta_chunked import gated_delta_chunked  # noqa: E402


def inputs(T, B=1, Hk=2, Hv=4, Dk=32, Dv=16, seed=0, with_state=True):
    mx.random.seed(seed)
    q = mx.random.normal((B, T, Hk, Dk))
    k = mx.random.normal((B, T, Hk, Dk))
    q = q / mx.linalg.norm(q, axis=-1, keepdims=True) * Dk**-0.5
    k = k / mx.linalg.norm(k, axis=-1, keepdims=True)
    v = mx.random.normal((B, T, Hv, Dv))
    g = mx.random.uniform(0.6, 1.0, (B, T, Hv))
    beta = mx.random.uniform(0.0, 1.0, (B, T, Hv))
    state = mx.random.normal((B, Hv, Dv, Dk)) * 0.1 if with_state else None
    return q, k, v, g, beta, state


@pytest.mark.parametrize("T,chunk", [(1, 64), (37, 16), (64, 64), (150, 64)])
def test_forward_matches_sequential_reference(T, chunk):
    q, k, v, g, beta, state = inputs(T)
    y_ref, s_ref = gd.gated_delta_ops(q, k, v, g, beta, state)
    y, s = gated_delta_chunked(q, k, v, g, beta, state, chunk_size=chunk)
    assert y.shape == y_ref.shape and s.shape == s_ref.shape
    assert mx.allclose(y, y_ref, atol=1e-4, rtol=1e-4).item()
    assert mx.allclose(s, s_ref, atol=1e-4, rtol=1e-4).item()


def test_without_initial_state():
    q, k, v, g, beta, _ = inputs(70, with_state=False)
    y_ref, s_ref = gd.gated_delta_ops(q, k, v, g, beta, None)
    y, s = gated_delta_chunked(q, k, v, g, beta, None, chunk_size=32)
    assert mx.allclose(y, y_ref, atol=1e-4, rtol=1e-4).item() and mx.allclose(s, s_ref, atol=1e-4, rtol=1e-4).item()


def test_gradients_match_sequential_reference():
    q, k, v, g, beta, state = inputs(90, seed=1)
    w = mx.random.normal((1, 90, 4, 16))

    def loss(fn):
        def f(q, k, v, g, beta, state):
            y, s = fn(q, k, v, g, beta, state)
            return (y * w).sum() + 0.1 * (s * s).sum()
        return mx.grad(f, argnums=(0, 1, 2, 3, 4, 5))

    ref = loss(gd.gated_delta_ops)(q, k, v, g, beta, state)
    got = loss(lambda *a: gated_delta_chunked(*a, chunk_size=32))(q, k, v, g, beta, state)
    for name, a, b in zip(["q", "k", "v", "g", "beta", "state"], ref, got, strict=True):
        assert mx.allclose(a, b, atol=2e-4, rtol=2e-3).item(), name


def test_default_chunk_is_stable_with_repeated_keys():
    """Real Qwen3.5 inputs on repetitive text made chunk 64 (and 32) diverge by up to 1e32: the WY inverse
    is built by repeated squaring and loses precision on long chunks of nearly identical keys."""
    q, k, v, g, beta, state = inputs(256, seed=2)
    k = mx.tile(k[:, :1], (1, 256, 1, 1))  # one key repeated: powers of the WY matrix grow binomially
    beta = mx.full(beta.shape, 1.0)
    g = mx.full(g.shape, 0.999)
    y_ref, s_ref = gd.gated_delta_ops(q, k, v, g, beta, state)
    y, s = gated_delta_chunked(q, k, v, g, beta, state)
    assert mx.allclose(y, y_ref, atol=1e-3, rtol=1e-3).item() and mx.allclose(s, s_ref, atol=1e-3, rtol=1e-3).item()
    y64, _ = gated_delta_chunked(q, k, v, g, beta, state, chunk_size=64)
    assert not mx.allclose(y64, y_ref, atol=1e-3, rtol=1e-3).item()  # why the default is not 64


def test_padding_mask_is_not_supported():
    q, k, v, g, beta, state = inputs(8)
    with pytest.raises(NotImplementedError):
        gated_delta_chunked(q, k, v, g, beta, state, mask=mx.ones((1, 8), dtype=mx.bool_))


def test_install_routes_only_the_training_path():
    from spike_train import gated_delta_chunked as gdc

    original = gd.gated_delta_ops
    try:
        gdc.install()
        q, k, v, g, beta, state = inputs(20)
        y, _ = gd.gated_delta_ops(q, k, v, g, beta, state)
        y_ref, _ = original(q, k, v, g, beta, state)
        assert gd.gated_delta_ops is not original and mx.allclose(y, y_ref, atol=1e-4).item()
        masked = mx.ones((1, 20), dtype=mx.bool_)  # padding masks still use mlx-lm's reference loop
        assert mx.allclose(gd.gated_delta_ops(q, k, v, g, beta, state, masked)[0],
                           original(q, k, v, g, beta, state, masked)[0]).item()
    finally:
        gd.gated_delta_ops = original


def test_train_sh_trains_through_the_wrapper():
    root = Path(__file__).resolve().parents[1]
    script = (root / "training" / "train.sh").read_text()
    assert "training/lora.py" in script and "python -m mlx_lm.lora" not in script
    assert "gated_delta_chunked" in (root / "training" / "lora.py").read_text()
