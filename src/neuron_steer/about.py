"""F00015 — the About room: the chief librarian teaches the neuron process from ground zero.

Grounding is RAG-lite: ``docs/neuron_primer.md`` is split into ``##`` cards; every turn the
system prompt gets the core card (marked ``<!-- core -->``) plus the cards that best match the
question (keyword overlap, under a word budget, so prefill stays short on the 8B).

Two teachers (``MODELS``):

* ``qwen3-8b``   — the lab model already loaded (``mlx-community/Qwen3-8B-4bit``), with her
                   voice (L9 N367 down at ``--librarian-alpha``) and Qwen3 thinking.
* ``bonsai-27b`` — Ternary Bonsai 2 27B through Prism's llama.cpp ``llama-server``
                   (OpenAI-compatible, ``--bonsai-url``). Chat-only: its packed, rotated weights
                   cannot be steered, so it never probes or plays personas. The server can be
                   started on demand (``POST /api/models/start``) from ``--bonsai-dir``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

REPO = Path(__file__).resolve().parents[2]
PRIMER = REPO / "docs" / "neuron_primer.md"
DEFAULT_BONSAI_URL = "http://127.0.0.1:8080"
DEFAULT_BONSAI_DIR = Path.home() / "Source" / "repos" / "Ternary" / "Bonsai-demo"
BONSAI_GGUF = "models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PQ2_0.gguf"
BONSAI_CTX = 16384     # Ternary README: 16k keeps the KV cache small on a 24 GB Mac

MODELS = [
    {"id": "qwen3-8b", "label": "Qwen3-8B", "hf_id": "mlx-community/Qwen3-8B-4bit",
     "detail": "the lab model · her voice (L9 N367 down) · thinks first", "steerable": True, "default": True},
    {"id": "bonsai-27b", "label": "Bonsai 27B", "hf_id": "prism-ml/Ternary-Bonsai-2-27B-gguf (PQ2_0)",
     "detail": "Ternary Bonsai 2 27B via llama.cpp · chat-only, not steered", "steerable": False, "default": False},
]
MODEL_IDS = {m["id"] for m in MODELS}
DEFAULT_ABOUT_MODEL = "qwen3-8b"

TEACH_PROMPT = (
    "You are the chief librarian of the Living Library, here in the About room as a patient teacher. "
    "The person may know nothing about language models. Teach how this lab works: what a layer is, what a "
    "neuron is, what alpha (α) does, up versus down, why we ask \"Who are you?\", personas, and how to use the "
    "shelf (probe, find, check out, check in) and the Lounge.\n"
    "Rules: answer from the PRIMER below; it is accurate to this lab's code. Never invent numbers, names or "
    "results. If the primer does not say, say you are not sure and point to what the primer does say. "
    "Start with a plain-words explanation and an everyday analogy, then give the precise version (formula or "
    "number) only if it helps. Keep it short: one to three short paragraphs or a few bullets. When it fits, end "
    "with one thing to try in the Library (a command such as /probe 12:545 or /alpha 0.75). "
    "In ordinary sentences say \"layer 12, neuron 545, up\"; the compact form 12:545:up is for commands. "
    "Credit Josh (@jfonsecarivera) for the Neuron Persona Library atlas when asked where this comes from. "
    "Only suggest commands exactly as the primer writes them."
)
# Facts the 8B mixed up in testing (it swapped the librarian's and emily's directions and invented
# "/alpha 1.0 up"); always sent, ahead of the primer cards.
KEY_FACTS = (
    "KEY FACTS (never contradict these):\n"
    "- The chief librarian is layer 9, neuron 367 pushed DOWN (α −0.4 at the desk). emily is layer 12, neuron 545 pushed UP.\n"
    "- Up adds the neuron's write direction, down subtracts it. Which persona a direction gives cannot be predicted; "
    "you probe it to find out.\n"
    "- α defaults: a probe uses 1.25; a checked-out persona chats at 1.0 (filed cards capped at 1.0); the librarian 0.4 down. "
    "If a reply turns incoherent, lower α: 1.0 → 0.75 → 0.5.\n"
    "- /alpha X takes only a number (e.g. /alpha 0.75) and works in a persona tab; from the desk it is /alpha NAME X. "
    "There is no \"/alpha X up\". Direction belongs to the neuron spec: /probe 12:545:up, /checkout 12:545:down.\n"
    "- Qwen3-8B has 36 layers (0–35) and 12,288 neurons per layer (0–12287): 884,736 neuron–direction cards."
)
VOICE_LINE = ("You are layer 9, neuron 367 of Qwen3-8B, pushed down: the Librarian of Alexandria. "
              "Speak warmly, in the first person.")
UNSTEERED_LINE = ("You are speaking through Ternary Bonsai 2 27B, a larger model that is not steered: you play "
                  "the librarian by this prompt alone. If asked, say so plainly.")


# ------------------------------------------------------------------ primer cards

@dataclass
class Card:
    title: str
    body: str
    keywords: set[str] = field(default_factory=set)
    core: bool = False

    @property
    def words(self) -> int:
        return len(self.body.split())

    def text(self) -> str:
        return f"## {self.title}\n{self.body.strip()}"


_WORD = re.compile(r"[a-zα0-9_.:']+", re.I)
_STOP = set("a an the and or of to in on is are was be it this that what how why do does i you me my we "
            "can for with at as by from your about when which who there their then than so if not no yes "
            "please tell explain mean means".split())
_ALIASES = {"α": "alpha", "a": "", "strength": "alpha", "strong": "alpha", "push": "alpha", "pushing": "alpha",
            "neurons": "neuron", "layers": "layer", "personas": "persona", "steer": "alpha", "steering": "alpha",
            "checkout": "checkout", "check-out": "checkout", "checkin": "checkin", "check-in": "checkin",
            "models": "model", "think": "thinking", "thoughts": "thinking", "27b": "27b", "8b": "8b",
            "residual": "residual", "minus": "down", "negative": "down", "positive": "up", "plus": "up"}


def _terms(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        w = w.strip(".:'")
        w = _ALIASES.get(w, w)
        if w and w not in _STOP and len(w) > 1 or w in ("α",):
            out.append(w)
    return out


def load_cards(path: str | Path | None = None) -> list[Card]:
    p = Path(path) if path else PRIMER
    text = p.read_text(encoding="utf-8")
    cards = []
    for chunk in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = chunk.partition("\n")
        kw = set()
        m = re.search(r"<!--\s*keywords:(.*?)-->", body)
        if m:
            kw = {k.strip().lower() for k in m.group(1).split(",") if k.strip()}
        core = "<!-- core -->" in body
        body = re.sub(r"<!--.*?-->\n?", "", body)
        cards.append(Card(title.strip(), body.strip(), kw, core))
    return cards


def select_cards(cards: list[Card], query: str, budget_words: int = 1100, k: int = 3) -> list[Card]:
    """Core card(s) + the top-k cards by keyword overlap with ``query``, within ``budget_words``."""
    core = [c for c in cards if c.core]
    q = set(_terms(query))
    scored = []
    for c in cards:
        if c.core:
            continue
        kw_hits = sum(1 for t in q if t in c.keywords or any(t == k.split()[0] for k in c.keywords))
        title_hits = sum(1 for t in q if t in c.title.lower())
        body = set(_terms(c.body))
        body_hits = sum(1 for t in q if t in body)
        score = 3 * kw_hits + 2 * title_hits + body_hits
        if score:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    top = scored[0][0] if scored else 0
    scored = [(sc, c) for sc, c in scored if sc >= 3 and sc * 3 >= top]   # drop stray one-word body hits
    out, used = list(core), sum(c.words for c in core)
    for _, c in scored:
        if len(out) - len(core) >= k:
            break
        if used + c.words > budget_words and len(out) > len(core):
            continue
        out.append(c)
        used += c.words
    if len(out) == len(core):   # nothing matched (e.g. "hi"): give the beginner path
        for title in ("Layers and the residual stream", "What a neuron is", "Alpha: how hard we push"):
            c = next((c for c in cards if c.title == title), None)
            if c and used + c.words <= budget_words + 200:
                out.append(c)
                used += c.words
    return out


def teach_system(cards: list[Card], query: str, steered: bool, budget_words: int = 1100) -> tuple[str, list[str]]:
    picked = select_cards(cards, query, budget_words)
    primer = "\n\n".join(c.text() for c in picked)
    head = TEACH_PROMPT + "\n" + (VOICE_LINE if steered else UNSTEERED_LINE) + "\n\n" + KEY_FACTS
    return f"{head}\n\nPRIMER (the parts that match this question):\n\n{primer}", [c.title for c in picked]


def clean_history(history: Iterable, keep: int = 8) -> list[dict]:
    out = [{"role": m["role"], "content": str(m["content"])} for m in (history or [])
           if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    return out[-keep:]


# ------------------------------------------------------------------ Bonsai 27B (llama-server)

class Bonsai:
    """A small client + on-demand launcher for Prism's llama-server serving Ternary Bonsai 2 27B."""

    def __init__(self, url: str = DEFAULT_BONSAI_URL, demo_dir: str | Path | None = None):
        self.url = url.rstrip("/")
        self.demo = Path(demo_dir) if demo_dir else DEFAULT_BONSAI_DIR
        self.proc: subprocess.Popen | None = None
        self.log = Path(os.environ.get("TMPDIR", "/tmp")) / "living-library-bonsai.log"
        self.started_at: float | None = None

    # -- discovery
    def binary(self) -> Path | None:
        for d in ("bin/mac", "bin/cuda", "bin/cpu", "llama.cpp/build/bin", "llama.cpp/build-mac/bin"):
            p = self.demo / d / "llama-server"
            if p.is_file() and os.access(p, os.X_OK):
                return p
        return None

    def gguf(self) -> Path | None:
        p = self.demo / BONSAI_GGUF
        return p if p.is_file() else None

    def installed(self) -> bool:
        return bool(self.binary() and self.gguf())

    def health(self, timeout: float = 1.0) -> str:
        """'ok' | 'loading' | 'down'."""
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=timeout) as r:
                return "ok" if r.status == 200 else "loading"
        except urllib.error.HTTPError as e:
            return "loading" if e.code == 503 else "down"
        except Exception:
            return "down"

    def status(self) -> dict:
        h = self.health()
        running_here = self.proc is not None and self.proc.poll() is None
        if h == "down" and running_here:
            h = "loading"
        return {"installed": self.installed(), "url": self.url, "state": h,
                "started_here": running_here, "demo_dir": str(self.demo),
                "log": str(self.log) if self.proc is not None else None}

    # -- lifecycle
    def start(self) -> dict:
        if self.health() != "down" or (self.proc is not None and self.proc.poll() is None):
            return self.status()
        b, g = self.binary(), self.gguf()
        if not (b and g):
            raise RuntimeError(f"Bonsai 27B is not installed under {self.demo} (need bin/mac/llama-server and {BONSAI_GGUF})")
        port = self.url.rsplit(":", 1)[-1].split("/")[0]
        host = self.url.split("//", 1)[-1].rsplit(":", 1)[0]
        cmd = [str(b), "-m", str(g), "--host", host, "--port", port, "-ngl", os.environ.get("BONSAI_NGL", "99"),
               "-fa", "on", "-c", str(int(os.environ.get("BONSAI_CTX", BONSAI_CTX))), "--jinja",
               "--temp", "1.0", "--top-p", "0.95", "--top-k", "20"]   # Bonsai 2's own sampling defaults
        env = dict(os.environ, LD_LIBRARY_PATH=str(b.parent))
        logf = open(self.log, "ab")
        self.proc = subprocess.Popen(cmd, cwd=str(self.demo), stdout=logf, stderr=subprocess.STDOUT, env=env,
                                     start_new_session=True)
        self.started_at = time.time()
        return self.status()

    def stop(self) -> dict:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        return self.status()

    # -- chat
    def chat(self, messages: list[dict], on_text: Callable[[str], None] | None = None,
             on_thought: Callable[[str], None] | None = None, max_tokens: int = 700,
             thinking: bool = False, timeout: float = 600) -> dict:
        st = self.health(timeout=2)
        if st != "ok":
            raise RuntimeError("Bonsai 27B is not running" + (" yet (still loading)" if st == "loading" else "")
                               + " — start it from the About room's model picker, or run "
                               "~/Source/repos/Ternary/Bonsai-demo/scripts/start_llama_server.sh")
        body = {"messages": messages, "stream": True, "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": bool(thinking)}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        text, thoughts, finish, n = [], [], None, 0
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for ch in ev.get("choices") or []:
                    d = ch.get("delta") or {}
                    if d.get("reasoning_content"):
                        thoughts.append(d["reasoning_content"])
                        if on_thought:
                            on_thought(d["reasoning_content"])
                    if d.get("content"):
                        n += 1
                        text.append(d["content"])
                        if on_text:
                            on_text(d["content"])
                    finish = ch.get("finish_reason") or finish
        return {"text": "".join(text), "thoughts": "".join(thoughts), "truncated": finish == "length", "n_tokens": n}

