"""Core steering: load Qwen3, measure r_L, install down_proj pre-hooks, generate.

Method (https://qwen-neurons-site.vercel.app/):

    h_L <- h_L + c * W_down[:, n]
    c    = sign * alpha * r_L / ||W_down[:, n]||
    r_L  = median residual-stream norm after layer L over the prompt's tokens
           (first token excluded)

Adding ``c`` to the down_proj *input* at index ``n`` adds exactly
``c * W_down[:, n]`` to the MLP output, and therefore to the residual stream
after layer L. In ``raw`` mode ``c`` is just the given float (no normalisation).
"""

from __future__ import annotations

import json
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import torch

from .prompts import Message, render_chat, strip_think

DEFAULT_MODEL = "Qwen/Qwen3-8B"
DEFAULT_ALPHA = 1.25


# --------------------------------------------------------------------------- steers


@dataclass(frozen=True)
class Steer:
    """One neuron push. ``alpha`` is signed: + pushes up, - pushes down.

    With ``raw=True`` alpha is a fixed amount added to the activation
    (e.g. 20.0), without residual-norm normalisation.
    """

    layer: int
    neuron: int
    alpha: float = DEFAULT_ALPHA
    raw: bool = False

    def __str__(self) -> str:
        mode = "raw" if self.raw else "α"
        return f"L{self.layer} N{self.neuron} {mode}={self.alpha:+g}"


def _parse_direction(value: Any) -> float:
    if isinstance(value, (int, float)):
        return 1.0 if value >= 0 else -1.0
    v = str(value).strip().lower()
    if v in {"up", "+", "+1", "1", "pos", "positive"}:
        return 1.0
    if v in {"down", "-", "-1", "neg", "negative"}:
        return -1.0
    raise ValueError(f"bad direction {value!r}; use up/down or +1/-1")


def parse_steer(spec: str, raw: bool = False) -> Steer:
    """Parse ``L:N[:ALPHA]`` or ``L,N[,ALPHA]``.

    ALPHA may be a signed float (``+1.25``, ``-1``) or ``up``/``down``
    (= ±1.25). Omitted ALPHA means ``+1.25``.
    """
    sep = ":" if ":" in spec else ","
    parts = [p.strip() for p in spec.split(sep)]
    if len(parts) not in (2, 3):
        raise ValueError(f"bad steer {spec!r}; expected LAYER:NEURON[:ALPHA] or LAYER,NEURON[,ALPHA]")
    layer, neuron = int(parts[0]), int(parts[1])
    alpha = DEFAULT_ALPHA
    if len(parts) == 3:
        try:
            alpha = float(parts[2])
        except ValueError:
            alpha = _parse_direction(parts[2]) * DEFAULT_ALPHA
    return Steer(layer, neuron, alpha, raw)


def load_steers_json(path: str | Path, force_raw: bool = False) -> list[Steer]:
    """Load ``[{layer, neuron, alpha, direction, [raw], [name]}, ...]``.

    ``alpha`` is a magnitude (its sign is ignored when ``direction`` is given);
    ``direction`` is up/down/+1/-1 (default up). Extra keys (name, note) are ignored.
    A top-level ``{"steers": [...]}`` object is also accepted.
    """
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = data.get("steers", [])
    steers: list[Steer] = []
    for i, item in enumerate(data):
        try:
            alpha = float(item.get("alpha", DEFAULT_ALPHA))
            if "direction" in item:
                alpha = abs(alpha) * _parse_direction(item["direction"])
            steers.append(
                Steer(
                    layer=int(item["layer"]),
                    neuron=int(item["neuron"]),
                    alpha=alpha,
                    raw=force_raw or bool(item.get("raw", False)),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"{path}: entry {i} invalid ({e}): {item!r}") from e
    return steers


@dataclass
class AppliedSteer:
    steer: Steer
    c: float
    r_L: float | None = None
    w_norm: float | None = None

    def __str__(self) -> str:
        if self.steer.raw:
            return f"{self.steer}  -> c={self.c:+.3f}"
        return f"{self.steer}  r_L={self.r_L:.2f} ‖W_down[:,n]‖={self.w_norm:.4f}  -> c={self.c:+.3f}"


@dataclass
class GenerationResult:
    text: str
    applied: list[AppliedSteer] = field(default_factory=list)
    n_new_tokens: int = 0
    stopped_on_repeat: bool = False
    thoughts: str = ""  # private reasoning (<think>…</think>) kept apart from the spoken ``text``


# --------------------------------------------------------------------- device/dtype


def pick_device(device: str = "auto") -> str:
    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def pick_dtype(device: str, dtype: str | None = None) -> torch.dtype:
    if dtype:
        return {"bfloat16": torch.bfloat16, "bf16": torch.bfloat16, "float16": torch.float16,
                "fp16": torch.float16, "float32": torch.float32, "fp32": torch.float32}[dtype]
    if device == "cuda":
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    if device == "mps":
        try:  # bf16 on MPS needs macOS 14+ / recent torch
            torch.zeros(1, dtype=torch.bfloat16, device="mps")
            return torch.bfloat16
        except Exception:
            return torch.float16
    return torch.bfloat16


# ----------------------------------------------------------------- repeat stopping


class RepeatStop:
    """Stop when the generated tail is an exact repeat of the block before it.

    Mirrors the site's "stops early if the reply repeats exactly". Only blocks of
    at least ``min_block`` tokens count, so short legit repeats don't trigger.
    """

    def __init__(self, prompt_len: int, min_block: int = 8):
        self.prompt_len = prompt_len
        self.min_block = min_block
        self.triggered = False

    def __call__(self, input_ids: torch.LongTensor, scores: Any, **kwargs: Any) -> bool:
        gen = input_ids[0, self.prompt_len:].tolist()
        n = len(gen)
        for w in range(self.min_block, n // 2 + 1):
            if gen[-w:] == gen[-2 * w:-w]:
                self.triggered = True
                return True
        return False


# ------------------------------------------------------------------------ main class


class NeuronSteer:
    """Load a Qwen3 model once and run steered / unsteered generations."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "auto", dtype: str | None = None):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import transformers

        self.model_name = model_name
        self.device = pick_device(device)
        self.dtype = pick_dtype(self.device, dtype)

        if self.device == "cuda":
            device_map: Any = "auto"
        else:
            device_map = {"": self.device}

        # transformers >= 4.56 renamed torch_dtype -> dtype
        ver = tuple(int(x) for x in transformers.__version__.split(".")[:2] if x.isdigit())
        dtype_kw = "dtype" if ver >= (4, 56) else "torch_dtype"

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, device_map=device_map, low_cpu_mem_usage=True, **{dtype_kw: self.dtype}
        )
        self.model.eval()
        self._rl_cache: dict[tuple[int, ...], dict[int, float]] = {}

    # -- model introspection ------------------------------------------------------

    @property
    def layers(self) -> Any:
        return self.model.model.layers

    @property
    def n_layers(self) -> int:
        return len(self.layers)

    @property
    def n_neurons(self) -> int:
        return int(self.model.config.intermediate_size)

    @property
    def input_device(self) -> torch.device:
        return self.model.get_input_embeddings().weight.device

    def validate(self, steers: list[Steer]) -> None:
        for s in steers:
            if not 0 <= s.layer < self.n_layers:
                raise ValueError(f"{s}: layer must be in [0, {self.n_layers - 1}]")
            if not 0 <= s.neuron < self.n_neurons:
                raise ValueError(f"{s}: neuron must be in [0, {self.n_neurons - 1}]")

    def encode(self, messages: list[Message]) -> torch.Tensor:
        text = render_chat(self.tokenizer, messages, enable_thinking=False)
        ids = self.tokenizer(text, return_tensors="pt", add_special_tokens=False).input_ids
        return ids.to(self.input_device)

    # -- r_L ------------------------------------------------------------------------

    @torch.no_grad()
    def residual_norms(self, input_ids: torch.Tensor, layers: set[int] | list[int]) -> dict[int, float]:
        """Median ‖h_L‖ after each requested layer over prompt tokens (first token excluded).

        Measured on an *unsteered* forward pass (call before installing hooks).
        Captured via forward hooks on the decoder layers themselves, so the last
        layer's value is pre-final-norm (unlike ``hidden_states[-1]``).
        """
        key = tuple(input_ids[0].tolist())
        cached = self._rl_cache.get(key, {})
        wanted = sorted(set(layers) - set(cached))
        if wanted:
            captured: dict[int, float] = {}
            handles = []

            def make_hook(L: int):
                def hook(_mod: Any, _args: Any, output: Any) -> None:
                    h = output[0] if isinstance(output, (tuple, list)) else output
                    norms = h[0, 1:].float().norm(dim=-1)  # exclude first token
                    if norms.numel() == 0:
                        norms = h[0].float().norm(dim=-1)
                    captured[L] = float(norms.median().item())
                return hook

            try:
                for L in wanted:
                    handles.append(self.layers[L].register_forward_hook(make_hook(L)))
                self.model(input_ids=input_ids, use_cache=False)
            finally:
                for h in handles:
                    h.remove()
            cached = {**cached, **captured}
            self._rl_cache[key] = cached
        return {L: cached[L] for L in layers}

    @torch.no_grad()
    def down_col_norm(self, layer: int, neuron: int) -> float:
        w = self.layers[layer].mlp.down_proj.weight  # [hidden, intermediate]
        return float(w[:, neuron].float().norm().item())

    def coefficients(self, steers: list[Steer], input_ids: torch.Tensor) -> list[AppliedSteer]:
        self.validate(steers)
        norm_layers = {s.layer for s in steers if not s.raw}
        r = self.residual_norms(input_ids, norm_layers) if norm_layers else {}
        out: list[AppliedSteer] = []
        for s in steers:
            if s.raw:
                out.append(AppliedSteer(s, c=s.alpha))
            else:
                wn = self.down_col_norm(s.layer, s.neuron)
                out.append(AppliedSteer(s, c=s.alpha * r[s.layer] / wn, r_L=r[s.layer], w_norm=wn))
        return out

    # -- hooks ----------------------------------------------------------------------

    @contextmanager
    def hooks(self, applied: list[AppliedSteer]) -> Iterator[None]:
        """Install one down_proj forward_pre_hook per layer; always removed on exit."""
        per_layer: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for a in applied:
            per_layer[a.steer.layer][a.steer.neuron] += a.c  # duplicates accumulate

        handles = []
        try:
            for L, adds in per_layer.items():
                mod = self.layers[L].mlp.down_proj
                dev = mod.weight.device
                idx = torch.tensor(list(adds.keys()), dtype=torch.long, device=dev)
                val = torch.tensor(list(adds.values()), dtype=torch.float32, device=dev)

                def pre_hook(_mod: Any, args: tuple, idx: torch.Tensor = idx, val: torch.Tensor = val) -> tuple:
                    x = args[0].clone()
                    x[..., idx] += val.to(x.dtype)
                    return (x, *args[1:])

                handles.append(mod.register_forward_pre_hook(pre_hook))
            yield
        finally:
            for h in handles:
                h.remove()

    # -- generation -----------------------------------------------------------------

    @torch.no_grad()
    def generate(
        self,
        messages: list[Message],
        steers: list[Steer] | None = None,
        max_new_tokens: int = 160,
        temperature: float = 0.0,
        top_p: float = 1.0,
        repeat_stop: bool = True,
    ) -> GenerationResult:
        from transformers import StoppingCriteriaList

        steers = steers or []
        input_ids = self.encode(messages)
        applied = self.coefficients(steers, input_ids) if steers else []

        stopper = RepeatStop(prompt_len=input_ids.shape[1])
        gen_kwargs: dict[str, Any] = dict(
            max_new_tokens=max_new_tokens,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
            stopping_criteria=StoppingCriteriaList([stopper]) if repeat_stop else None,
        )
        # Qwen3 generation_config ships an <|im_end|> eos list; keep it if present.
        cfg_eos = getattr(self.model.generation_config, "eos_token_id", None)
        if cfg_eos is not None:
            gen_kwargs["eos_token_id"] = cfg_eos
        if temperature > 0:
            gen_kwargs.update(do_sample=True, temperature=temperature, top_p=top_p)
        else:  # greedy; null out sampling defaults from generation_config
            gen_kwargs.update(do_sample=False, temperature=None, top_p=None, top_k=None)

        attn = torch.ones_like(input_ids)
        with self.hooks(applied):
            out = self.model.generate(input_ids=input_ids, attention_mask=attn, **gen_kwargs)

        new = out[0, input_ids.shape[1]:]
        text = strip_think(self.tokenizer.decode(new, skip_special_tokens=True))
        return GenerationResult(text, applied, int(new.numel()), stopper.triggered)
