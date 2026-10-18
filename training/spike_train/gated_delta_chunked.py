"""Chunk-parallel gated delta rule for training Qwen3.5 linear-attention layers with mlx.

mlx-lm runs the recurrence with a Metal kernel for inference, but that kernel has no backward pass, so in
training mode it falls back to `gated_delta_ops`: one small graph step per token, which made one LoRA step on a
~400-token chat take ~9.5 s on an M4 Max. This is the same recurrence in the chunked form used by
flash-linear-attention (WY representation): within a chunk everything is matrix products, and only the chunk
boundaries are sequential. It is built from differentiable mlx ops, so mlx derives the backward pass.

The intra-chunk WY inverse (I - A)^-1 is built by repeated squaring, which is all matmuls but cancels
catastrophically on long chunks of near-identical keys (real Qwen3.5 activations on repetitive text diverged
by up to 1e32 at chunk 64 and 0.2 at chunk 32), so chunks are 16 tokens.

Recurrence (per head, mlx-lm's layout, state S is [Dv, Dk]):
    S_t = g_t S_{t-1} + beta_t (v_t - g_t S_{t-1} k_t) k_t^T,    y_t = S_t q_t
"""

from __future__ import annotations

import math

import mlx.core as mx


def gated_delta_chunked(q, k, v, g, beta, state=None, mask=None, chunk_size: int = 16):
    """Drop-in for `mlx_lm.models.gated_delta.gated_delta_ops` with scalar gating and no padding mask.

    Shapes: q, k [B, T, Hk, Dk]; v [B, T, Hv, Dv]; g, beta [B, T, Hv]; state [B, Hv, Dv, Dk] or None.
    Returns y [B, T, Hv, Dv] (in q's dtype) and the final state [B, Hv, Dv, Dk] (float32).
    """
    if mask is not None:
        raise NotImplementedError("padding masks are not supported; train with batch_size 1")
    if g.ndim != 3:
        raise NotImplementedError("only scalar (per-head) gating is supported")
    B, T, Hk, Dk = q.shape
    Hv, Dv = v.shape[-2:]
    out_dtype = q.dtype
    if (r := Hv // Hk) > 1:
        q, k = mx.repeat(q, r, -2), mx.repeat(k, r, -2)

    f32 = mx.float32
    q, k, v = (x.transpose(0, 2, 1, 3).astype(f32) for x in (q, k, v))  # [B, H, T, D]
    beta = beta.transpose(0, 2, 1).astype(f32)
    log_g = mx.log(mx.maximum(g.astype(f32), 1e-30)).transpose(0, 2, 1)  # [B, H, T]

    C = chunk_size
    pad = (-T) % C
    if pad:  # padded steps have k = 0, beta = 0 and decay 1: they leave the state unchanged
        q, k, v = (mx.pad(x, [(0, 0), (0, 0), (0, pad), (0, 0)]) for x in (q, k, v))
        beta, log_g = (mx.pad(x, [(0, 0), (0, 0), (0, pad)]) for x in (beta, log_g))
    n = (T + pad) // C
    q, k, v = (x.reshape(B, Hv, n, C, x.shape[-1]) for x in (q, k, v))
    beta, log_g = (x.reshape(B, Hv, n, C) for x in (beta, log_g))

    gc = mx.cumsum(log_g, axis=-1)  # log of the decay from the chunk start up to and including t
    idx = mx.arange(C)
    lower = (idx[:, None] >= idx[None, :]).astype(f32)
    strict = (idx[:, None] > idx[None, :]).astype(f32)
    diff = gc[..., :, None] - gc[..., None, :]
    decay = mx.exp(diff * lower) * lower  # exp(gc_i - gc_j) for j <= i, else 0 (no inf in the backward pass)

    kb = k * beta[..., None]
    vb = v * beta[..., None]
    a = -(kb @ k.swapaxes(-1, -2)) * decay * strict
    # (I - a)^-1 for strictly lower-triangular a: (I + a)(I + a^2)(I + a^4)... as a^C = 0
    eye = mx.eye(C, dtype=f32)
    t_inv, power = eye + a, a
    for _ in range(max(0, math.ceil(math.log2(C)) - 1)):
        power = power @ power
        t_inv = t_inv @ (eye + power)
    u = t_inv @ vb  # [B, H, n, C, Dv]
    w = t_inv @ (kb * mx.exp(gc)[..., None])  # [B, H, n, C, Dk]

    s = mx.zeros((B, Hv, Dk, Dv), dtype=f32) if state is None else state.astype(f32).swapaxes(-1, -2)
    ys = []
    for i in range(n):
        qi, ki, gi = q[:, :, i], k[:, :, i], gc[:, :, i]
        v_new = u[:, :, i] - w[:, :, i] @ s
        intra = (qi @ ki.swapaxes(-1, -2)) * decay[:, :, i]
        ys.append((qi * mx.exp(gi)[..., None]) @ s + intra @ v_new)
        g_last = gi[..., -1:]
        s = s * mx.exp(g_last)[..., None] + (ki * mx.exp(g_last - gi)[..., None]).swapaxes(-1, -2) @ v_new
    y = mx.concatenate(ys, axis=2)[:, :, :T]
    return y.transpose(0, 2, 1, 3).astype(out_dtype), s.swapaxes(-1, -2)


def install(chunk_size: int = 16) -> None:
    """Make mlx-lm's training path (use_kernel=False) use the chunked form. Inference keeps the Metal kernel;
    calls with a padding mask or vector gating still go to mlx-lm's sequential reference."""
    from mlx_lm.models import gated_delta

    reference = gated_delta.gated_delta_ops

    def ops(q, k, v, g, beta, state=None, mask=None):
        if mask is not None or g.ndim != 3:
            return reference(q, k, v, g, beta, state, mask)
        return gated_delta_chunked(q, k, v, g, beta, state, chunk_size=chunk_size)

    ops.reference = reference
    gated_delta.gated_delta_ops = ops
