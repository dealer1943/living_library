"""MLX backend (Apple Silicon, quantized e.g. 4-bit Qwen3-8B) for the same steering method.

Same math as :mod:`neuron_steer.steer`:

    c   = sign * alpha * r_L / ||W_down[:, n]||      (raw mode: c = alpha)
    add c at index n of the down_proj *input* (post silu(gate)*up)

Steering is applied by temporarily swapping ``layers[L].mlp.down_proj`` for a
wrapper module that adds a dense bias vector to its input on every forward
(prompt prefill and each decoded token). ``‖W_down[:, n]‖`` is computed from the
*dequantized* weight, i.e. exactly the effective weight MLX uses in the matmul.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import mlx.core as mx
import mlx.nn as nn

from .prompts import Message, render_chat, strip_think
from .steer import AppliedSteer, GenerationResult, Steer

DEFAULT_MLX_MODEL = "mlx-community/Qwen3-8B-4bit"


def is_mlx_model(name: str) -> bool:
    n = name.lower()
    return n.startswith("mlx-community/") or "mlx" in n


class _SteeredDown(nn.Module):
    """down_proj wrapper: inner(x + add)."""

    def __init__(self, inner: nn.Module, add: mx.array):
        super().__init__()
        self.inner = inner
        self.add = add

    def __call__(self, x: mx.array) -> mx.array:
        return self.inner(x + self.add.astype(x.dtype))


class _Capture(nn.Module):
    """Decoder-layer wrapper that records the median residual norm of its output."""

    def __init__(self, inner: nn.Module, sink: dict, L: int):
        super().__init__()
        self.inner = inner
        self._sink = sink
        self._L = L

    def __call__(self, x: mx.array, *args: Any, **kwargs: Any) -> mx.array:
        out = self.inner(x, *args, **kwargs)
        h = out[0].astype(mx.float32)
        h = h[1:] if h.shape[0] > 1 else h  # exclude first token
        norms = mx.sqrt((h * h).sum(axis=-1))
        self._sink[self._L] = float(_median(norms))
        return out


def _median(x: mx.array) -> float:
    s = mx.sort(x.reshape(-1))
    n = s.shape[0]
    return float((s[(n - 1) // 2] + s[n // 2]) / 2)


class MLXNeuronSteer:
    """Drop-in counterpart of :class:`neuron_steer.steer.NeuronSteer` using mlx-lm."""

    supports_streaming = True  # generate(..., on_text=cb) calls cb with each decoded text piece

    def __init__(self, model_name: str = DEFAULT_MLX_MODEL, **_: Any):
        from mlx_lm import load

        self.model_name = model_name
        self.model, self.tokenizer = load(model_name)
        self.device = f"mlx:{mx.default_device()}"
        q = self.layers[0].mlp.down_proj
        self.dtype = f"{getattr(q, 'bits', 16)}-bit" if isinstance(q, nn.QuantizedLinear) else "float"
        self._rl_cache: dict[tuple[int, ...], dict[int, float]] = {}
        self._wn_cache: dict[tuple[int, int], float] = {}

    @property
    def layers(self) -> list:
        return self.model.model.layers

    @property
    def n_layers(self) -> int:
        return len(self.layers)

    @property
    def n_neurons(self) -> int:
        return int(self.model.args.intermediate_size)

    def validate(self, steers: list[Steer]) -> None:
        for s in steers:
            if not 0 <= s.layer < self.n_layers:
                raise ValueError(f"{s}: layer must be in [0, {self.n_layers - 1}]")
            if not 0 <= s.neuron < self.n_neurons:
                raise ValueError(f"{s}: neuron must be in [0, {self.n_neurons - 1}]")

    def encode(self, messages: list[Message]) -> list[int]:
        text = render_chat(self.tokenizer, messages, enable_thinking=False)
        return list(self.tokenizer.encode(text, add_special_tokens=False))

    # -- r_L / ‖W_down[:,n]‖ ----------------------------------------------------------

    def residual_norms(self, ids: list[int], layers: set[int] | list[int]) -> dict[int, float]:
        key = tuple(ids)
        cached = self._rl_cache.get(key, {})
        wanted = sorted(set(layers) - set(cached))
        if wanted:
            sink: dict[int, float] = {}
            orig = {L: self.layers[L] for L in wanted}
            try:
                for L in wanted:
                    self.model.model.layers[L] = _Capture(orig[L], sink, L)
                mx.eval(self.model(mx.array([ids])))
            finally:
                for L, m in orig.items():
                    self.model.model.layers[L] = m
            cached = {**cached, **sink}
            self._rl_cache[key] = cached
        return {L: cached[L] for L in layers}

    def down_col_norm(self, layer: int, neuron: int) -> float:
        k = (layer, neuron)
        if k not in self._wn_cache:
            d = self.layers[layer].mlp.down_proj
            if isinstance(d, nn.QuantizedLinear):
                w = mx.dequantize(d.weight, d.scales, d.get("biases"), d.group_size, d.bits,
                                  **({"mode": d.mode} if hasattr(d, "mode") else {}))
            else:
                w = d.weight
            col = w[:, neuron].astype(mx.float32)  # [hidden]
            self._wn_cache[k] = float(mx.sqrt((col * col).sum()))
        return self._wn_cache[k]

    def coefficients(self, steers: list[Steer], ids: list[int]) -> list[AppliedSteer]:
        self.validate(steers)
        norm_layers = {s.layer for s in steers if not s.raw}
        r = self.residual_norms(ids, norm_layers) if norm_layers else {}
        out: list[AppliedSteer] = []
        for s in steers:
            if s.raw:
                out.append(AppliedSteer(s, c=s.alpha))
            else:
                wn = self.down_col_norm(s.layer, s.neuron)
                out.append(AppliedSteer(s, c=s.alpha * r[s.layer] / wn, r_L=r[s.layer], w_norm=wn))
        return out

    # -- hooks -----------------------------------------------------------------------

    @contextmanager
    def hooks(self, applied: list[AppliedSteer]) -> Iterator[None]:
        per_layer: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for a in applied:
            per_layer[a.steer.layer][a.steer.neuron] += a.c
        orig: dict[int, nn.Module] = {}
        try:
            for L, adds in per_layer.items():
                vec = [0.0] * self.n_neurons
                for n, c in adds.items():
                    vec[n] = c
                mlp = self.layers[L].mlp
                orig[L] = mlp.down_proj
                mlp.down_proj = _SteeredDown(orig[L], mx.array(vec, dtype=mx.float32))
            yield
        finally:
            for L, m in orig.items():
                self.layers[L].mlp.down_proj = m

    # -- generation ------------------------------------------------------------------

    def generate(
        self,
        messages: list[Message],
        steers: list[Steer] | None = None,
        max_new_tokens: int = 160,
        temperature: float = 0.0,
        top_p: float = 1.0,
        repeat_stop: bool = True,
        on_text: Callable[[str], None] | None = None,
    ) -> GenerationResult:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        steers = steers or []
        ids = self.encode(messages)
        applied = self.coefficients(steers, ids) if steers else []
        sampler = make_sampler(temp=temperature, top_p=top_p)

        gen: list[int] = []
        stopped = False
        with self.hooks(applied):
            for resp in stream_generate(self.model, self.tokenizer, mx.array(ids),
                                        max_tokens=max_new_tokens, sampler=sampler):
                if resp.finish_reason == "stop" and resp.token in self.tokenizer.eos_token_ids:
                    break
                gen.append(int(resp.token))
                if repeat_stop and _repeats(gen):
                    stopped = True
                    break
                if on_text is not None and resp.text:
                    on_text(resp.text)
        text = strip_think(self.tokenizer.decode(gen, skip_special_tokens=True))
        return GenerationResult(text, applied, len(gen), stopped)


def _repeats(gen: list[int], min_block: int = 8) -> bool:
    n = len(gen)
    return any(gen[-w:] == gen[-2 * w:-w] for w in range(min_block, n // 2 + 1))
