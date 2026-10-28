"""The chief librarian: an interactive REPL for probing, filing and looking up personas.

Layer 9 · Neuron 367 pushed *down* makes Qwen3-8B the Librarian of Alexandria. She is
the session's curator:

* probing: steer a (layer, neuron, direction), ask "Who are you?", show the reply,
  suggest a persona label from how the model identifies itself, and file the card;
* lookups by persona (``/find coffee bean``, or just ``show smallpox``);
* an inventory of which (layer, neuron, direction) cards are filed vs. untested.

Plain lines (no slash) are a conversation *with the librarian*: generated with only
L9:367:down (plus any ``/add`` extras) active, under a system prompt telling her what
she is the librarian *of* (:data:`SYSTEM_PROMPT`) and, unless ``/context off``, a short
note on what the catalogue holds. She thinks first (Qwen3 ``<think>…</think>``, capped at
``think_budget`` tokens) and only the words after it are her reply; the thoughts are kept
apart (``/thoughts`` in the REPL, a collapsed "Thoughts" disclosure in the web chat).
Probes never include her steer: each probe runs the probed neuron alone, thinking off.

:class:`LibrarianSession` holds the model-facing state (her steer, chat history,
catalogue note, probing) without any terminal I/O; the REPL (:class:`Librarian`) and
the web chat (:mod:`neuron_steer.web`) both drive one.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import dataclass, replace
from typing import Callable

from .library import (LIBRARIAN, Entry, Library, direction_of, guess_weirdness, suggest_persona)
from .steer import GenerationResult
from .prompts import DEFAULT_PROMPT, Message, split_reasoning, split_thoughts
from .steer import Steer, parse_steer

LIB = "Librarian ›"

# Who she is and what her library holds. Kept short: the steered model follows little more.
SYSTEM_PROMPT = (
    "You are the chief librarian. Your library is a catalogue of neuron personas: each card records who "
    "the AI model Qwen3-8B says it is (asked \"Who are you?\") when one MLP neuron is pushed up or down, "
    "filed by layer, neuron and direction. You are layer 9, neuron 367, pushed down: the Librarian of "
    "Alexandria. You curate the cards and help the person you are talking to find, file, name and remark "
    "on personas (commands: find NAME, show L N, inventory, /probe L:N:up|down). Reply to them directly, "
    "in the first person, in two to four sentences. You cannot change a checked-out persona's push strength "
    "(alpha) yourself: the person types /alpha X in that persona's tab."
)
DEFAULT_THINK_BUDGET = 512
DEFAULT_VOICE_NAME = "the Librarian of Alexandria"


def system_prompt(voice: Steer | None = None, name: str | None = None) -> str:
    """:data:`SYSTEM_PROMPT` for whoever is behind the desk (F00006). The default voice gets the
    original text; another neuron is told which card it is and that it now serves as chief librarian."""
    if voice is None or (voice.layer, voice.neuron, direction_of(voice.alpha)) == LIBRARIAN and not name:
        return SYSTEM_PROMPT
    d = direction_of(voice.alpha)
    who = f"layer {voice.layer}, neuron {voice.neuron}, pushed {d}" + (f": {name}" if name else "")
    return SYSTEM_PROMPT.replace("You are layer 9, neuron 367, pushed down: the Librarian of Alexandria.",
                                 f"You are {who}, and you now serve as the chief librarian.")

HELP = """\
probing & filing
  /probe L:N[:up|down|α]   ask "Who are you?" with that push and file the reply
                           (no direction = both, skipping cards already filed)
  /probe L:N[:dir] --alpha X   same with |α|=X (also -a X, alpha=X, L:N:up:X);
                           a signed X with no direction picks it: /probe 12:545 -a -0.5 = down
  /probe L:N … --prompt "Q"   ask Q instead of "Who are you?" under the same push
                           (also -p "Q", --prompt="Q", prompt="Q"; unquoted runs to the end of the line);
                           on an already-filed card it shows the reply but keeps the card (/probe! files it)
  /probe random [k]        probe k random untouched cards
  /probe! …                re-probe even if already filed (old reply kept in history)
  /alpha [X]               show / set the default probe magnitude (default 1.25)
  /flip L N [--alpha X] [--prompt "Q"]   probe both up and down
  /next [k]                probe the next k untested cards (finishes half-flipped neurons first)
the catalogue
  /find QUERY              persona lookup (persona/tags first, then reply text)  — or just: find QUERY
  /open L N [up|down]      show filed cards for a neuron (L12 N545, 12:545:up) — or just: show L N / show NAME
  /recent [k]   /personas  recent cards / all persona names with counts
  /inventory [L]           tested up/down counts, untested estimate, next suggestions
  /name L N DIR NAME       rename a card       /tag L N DIR t1 t2   /rate L N DIR 0..1   /note L N DIR text
  /forget L N DIR          remove a card
talking to the librarian (L9:367:down)
  plain text               chat with her     /reset  forget the chat     /context on|off  catalogue note
  /thoughts                her private thoughts behind the last reply
  /think on|off|K          let her think first (K = token budget, default 512; off = answer directly)
  /steers /add L:N[:α] /rm L:N /clear      extra steers stacked on her voice
  /voice on|off            let her remark (one generated line) after each filing
  /help  /quit"""


def _parse_dir(tok: str) -> tuple[str, float | None]:
    t = tok.strip().lower()
    if t in ("up", "+", "u"):
        return "up", None
    if t in ("down", "-", "d"):
        return "down", None
    a = float(t)
    return direction_of(a), abs(a)


_NEURON_REF = re.compile(r"^\s*L?(\d+)[\s:,/]+N?(\d+)(?:[\s:,/]+(up|down|u|d|\+|-))?\s*$", re.I)


def parse_neuron_ref(rest: str) -> tuple[int, int, str | None] | None:
    """``L12 N545 up`` | ``12 545`` | ``12:545:down`` | ``l12:n545`` -> (12, 545, dir|None);
    None if ``rest`` is not a layer/neuron reference (e.g. a persona name)."""
    m = _NEURON_REF.match(rest)
    if not m:
        return None
    d = m.group(3)
    return int(m.group(1)), int(m.group(2)), (_parse_dir(d)[0] if d else None)


def _looks_like_ref(rest: str) -> bool:
    """``L N``, ``L12``, ``12 N`` … : meant as a neuron reference but not a valid one."""
    w = rest.split()
    return bool(w) and len(w) <= 3 and all(re.fullmatch(r"[ln]\d*|\d+|up|down", x, re.I) for x in w[:2])


_ALPHA_FLAG = re.compile(
    r"(?:^|\s)(?:--alpha|-a|alpha|\u03b1)(?:\s*=\s*|\s+)([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", re.I)
_NUM = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
TARGET_USAGE = ("expected L:N[:up|down][:α] [--alpha X] [--prompt \"Q\"] — e.g. 12:545, 12:545:up:0.5, "
                "12:545 --alpha 0.5, 12 545 down -a 2, 12:545 -a 0.5 --prompt \"what is your story?\"")


_PROMPT_FLAG = re.compile(r"(?:^|\s)(?:--prompt|-p|prompt)(?:\s*=\s*|\s+)", re.I)
_QUOTES = {'"': '"', "'": "'", "\u201c": "\u201d", "\u2018": "\u2019"}


def _split_prompt(rest: str) -> tuple[str, str | None]:
    """Pull a custom probe question out of the /probe text -> (rest without it, prompt or None).

    ``12:545 --alpha 0.5 --prompt "what is your story?"`` | ``-p 'Q'`` | ``--prompt="Q"`` |
    ``prompt=Q`` | ``--prompt what is your story?`` (unquoted: to the end of the line, stopping
    before a trailing ``--alpha X`` / ``-a X``).
    """
    m = _PROMPT_FLAG.search(rest)
    if not m:
        return rest, None
    head, tail = rest[:m.start()], rest[m.end():]
    q = tail[:1]
    if q in _QUOTES:
        end = tail.find(_QUOTES[q], 1)
        if end < 0:
            raise ValueError("unterminated quote in --prompt")
        prompt, after = tail[1:end], tail[end + 1:]
    else:
        a = _ALPHA_FLAG.search(tail)
        prompt, after = (tail[:a.start()], tail[a.start():]) if a else (tail, "")
    prompt = prompt.strip()
    if not prompt:
        raise ValueError('empty --prompt; e.g. --prompt "what is your story?"')
    rest = head + " " + after
    if _PROMPT_FLAG.search(rest):
        raise ValueError("prompt given twice")
    return rest.strip(), prompt


def _parse_target(rest: str) -> tuple[int, int, list[tuple[str, float | None]]]:
    """``L:N[:up|down][:α] [--alpha|-a X]`` -> (L, N, [(dir, |α|?)...]).

    ``9:367:down`` | ``9,367,-1`` | ``9 367 up`` | ``9:367`` (both) | ``12:545:up:0.5`` |
    ``12:545 --alpha 0.5`` (both, |α|=0.5) | ``12:545 -a -0.5`` (signed, no direction: down only) |
    ``L12 N545 up --alpha=2``. A flag magnitude overrides one written in the target.
    """
    flag: str | None = None
    m = _ALPHA_FLAG.search(rest)
    if m:
        flag = m.group(1)
        rest = rest[:m.start()] + " " + rest[m.end():]
        if _ALPHA_FLAG.search(rest):
            raise ValueError("alpha given twice; " + TARGET_USAGE)
    parts = [p for p in rest.replace(":", " ").replace(",", " ").split() if p]
    parts[:2] = [p[1:] if p[:1].lower() in ("l", "n") and p[1:].isdigit() else p for p in parts[:2]]
    if len(parts) not in (2, 3, 4) or not all(p.isdigit() for p in parts[:2]):
        raise ValueError(TARGET_USAGE)
    L, N = int(parts[0]), int(parts[1])
    fa = abs(float(flag)) if flag is not None else None
    if len(parts) == 2:
        if flag is not None and flag[0] in "+-":       # signed alpha, no direction: that direction only
            return L, N, [(direction_of(float(flag)), fa)]
        return L, N, [("up", fa), ("down", fa)]
    d, a = _parse_dir(parts[2])
    if len(parts) == 4:
        if a is not None or not _NUM.match(parts[3]):
            raise ValueError(TARGET_USAGE)
        a = abs(float(parts[3]))
    return L, N, [(d, fa if fa is not None else a)]


@dataclass
class ProbeResult:
    """One un-filed probe: the steer pushed, the reply, and a suggested persona name."""
    layer: int
    neuron: int
    direction: str
    alpha: float
    steer: Steer
    result: GenerationResult
    persona: str
    prompt: str = DEFAULT_PROMPT


class LibrarianSession:
    """The Librarian of Alexandria without a terminal: her voice (L9:367:down at
    ``librarian_alpha``), any extra steers, a chat history, the catalogue note, and probing.

    Shared by the stdin REPL and the web server. Not thread-safe: callers serialise
    access (the web server runs every model call on one worker thread).
    """

    def __init__(self, lab, lib: Library, model: str, backend: str = "mlx", *,
                 librarian_alpha: float = 0.4, extra: list[Steer] | None = None,
                 context: bool = True, max_new_tokens: int = 160, temperature: float = 0.0,
                 top_p: float = 1.0, repeat_stop: bool = True, think_budget: int = DEFAULT_THINK_BUDGET):
        self.lab = lab
        self.lib = lib
        self.model = model
        self.backend = backend
        self.default_voice = Steer(LIBRARIAN[0], LIBRARIAN[1], -abs(librarian_alpha))
        self.voice_steer = self.default_voice
        self.voice_name: str | None = None
        self.extra: list[Steer] = list(extra or [])
        self.history: list[Message] = []
        self.context = context
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.repeat_stop = repeat_stop
        self.think_budget = think_budget
        self.last_thoughts = ""

    @classmethod
    def from_args(cls, lab, lib: Library, args: argparse.Namespace) -> "LibrarianSession":
        return cls(lab, lib, args.model, args.backend, librarian_alpha=args.librarian_alpha,
                   extra=getattr(args, "extra_steers", None), context=not args.no_context,
                   max_new_tokens=args.max_new_tokens, temperature=args.temperature,
                   top_p=args.top_p, repeat_stop=not args.no_repeat_stop,
                   think_budget=getattr(args, "think_budget", DEFAULT_THINK_BUDGET))

    def fork(self) -> "LibrarianSession":
        """A fresh conversation sharing the model, catalogue and settings."""
        s = LibrarianSession(self.lab, self.lib, self.model, self.backend, librarian_alpha=abs(self.default_voice.alpha),
                             extra=self.extra, context=self.context, max_new_tokens=self.max_new_tokens,
                             temperature=self.temperature, top_p=self.top_p, repeat_stop=self.repeat_stop,
                             think_budget=self.think_budget)
        return s

    @property
    def steers(self) -> list[Steer]:
        return [self.voice_steer, *self.extra]

    def set_voice(self, steer: Steer | None = None, name: str | None = None) -> Steer:
        """Put another neuron behind the librarian's desk (F00006); None restores L9 N367 down."""
        if steer is None:
            self.voice_steer, self.voice_name = self.default_voice, None
        else:
            self.lab.validate([steer])
            self.voice_steer, self.voice_name = steer, (name or None)
        return self.voice_steer

    def generate(self, messages: list[Message], steers: list[Steer], max_new_tokens: int | None = None,
                 on_text: Callable[[str], None] | None = None, think_budget: int = 0,
                 on_thought: Callable[[str], None] | None = None, assistant_prefix: str = "") -> GenerationResult:
        kw = dict(max_new_tokens=max_new_tokens or self.max_new_tokens, temperature=self.temperature,
                  top_p=self.top_p, repeat_stop=self.repeat_stop)
        if on_text is not None and getattr(self.lab, "supports_streaming", False):
            kw["on_text"] = on_text
        if think_budget > 0 and getattr(self.lab, "supports_thinking", False):
            kw["think_budget"] = think_budget
            if on_thought is not None:
                kw["on_thought"] = on_thought
        if assistant_prefix:
            kw["assistant_prefix"] = assistant_prefix
        return self.lab.generate(messages, steers, **kw)

    def catalogue_note(self) -> str:
        """Card counts and the most recent cards, so she knows what is on the shelves."""
        inv = self.lib.inventory(self.model)
        recent = self.lib.recent(12, model=self.model)
        shelf = "; ".join(f"{e.layer}:{e.neuron}:{e.direction} = {e.persona}" for e in recent) or "nothing yet"
        return (f"Catalogue of neuron personas: {inv.tested} cards filed "
                f"({inv.tested_up} up, {inv.tested_down} down) of {inv.total:,}. Recent cards: {shelf}.")

    def system(self) -> list[Message]:
        """Who she is (:data:`SYSTEM_PROMPT`), plus the catalogue note unless context is off."""
        text = system_prompt(self.voice_steer, self.voice_name) + (" " + self.catalogue_note() if self.context else "")
        return [{"role": "system", "content": text}]

    def chat(self, message: str, on_text: Callable[[str], None] | None = None,
             on_thought: Callable[[str], None] | None = None) -> GenerationResult:
        """One turn with her voice (L9:367:down + extras) active; appends both sides to history.

        ``result.text`` is only her spoken reply and ``result.thoughts`` her private reasoning
        (the <think> block, or untagged "Okay, the user is asking…" paragraphs split off the
        front of the reply). Only the reply goes into the history.
        """
        self.history.append({"role": "user", "content": message})
        try:
            res = self.generate(self.system() + self.history, self.steers, on_text=on_text,
                                think_budget=self.think_budget, on_thought=on_thought)
        except Exception:
            self.history.pop()
            raise
        res = _separate(res)
        self.last_thoughts = res.thoughts
        self.history.append({"role": "assistant", "content": res.text})
        return res

    def reset(self) -> None:
        self.history.clear()

    def probe(self, L: int, N: int, direction: str, alpha: float, prompt: str | None = None) -> ProbeResult:
        """Push (L, N, direction) alone — never with her voice — and ask ``prompt`` ("Who are you?")."""
        alpha = abs(alpha)
        prompt = (prompt or "").strip() or DEFAULT_PROMPT
        steer = Steer(L, N, alpha if direction == "up" else -alpha)
        self.lab.validate([steer])
        res = self.generate([{"role": "user", "content": prompt}], [steer])
        persona = suggest_persona(res.text)
        if (L, N, direction) == LIBRARIAN and "librar" in res.text.lower():
            persona = "chief librarian"
        return ProbeResult(L, N, direction, alpha, steer, res, persona, prompt)

    def file(self, p: ProbeResult, persona: str | None = None, tags: list[str] | None = None) -> Entry:
        r = p.result
        return self.lib.file_persona(Entry(
            layer=p.layer, neuron=p.neuron, direction=p.direction, alpha=p.alpha, reply=r.text,
            persona=persona or p.persona, model=self.model, backend=self.backend, prompt=p.prompt,
            tags=list(tags or []), weirdness=guess_weirdness(r.text, r.stopped_on_repeat),
            stopped_on_repeat=r.stopped_on_repeat, n_tokens=r.n_new_tokens))

    def remark(self, e: Entry) -> GenerationResult:
        msg = (f"A new card was just filed: {e.key} identifies as “{e.persona}”. "
               f"It said: {e.reply[:300]!r}. In one sentence, as the chief librarian, note it for the catalogue.")
        return _separate(self.generate([{"role": "user", "content": msg}], [self.voice_steer], max_new_tokens=60))


def _separate(res: GenerationResult) -> GenerationResult:
    """Make sure no thinking is left in ``res.text``: tagged blocks, then untagged reasoning."""
    tagged, text = split_thoughts(res.text)
    loose, text = split_reasoning(text)
    thoughts = "\n\n".join(t for t in (res.thoughts, tagged, loose) if t)
    return replace(res, text=text, thoughts=thoughts)


class Librarian:
    def __init__(self, lab, lib: Library, args: argparse.Namespace,
                 out: Callable[[str], None] = print, ask: Callable[[str], str] = input):
        self.lab = lab
        self.lib = lib
        self.args = args
        self.model = args.model
        self.backend = args.backend
        self.say_raw = out
        self.ask = ask
        self.alpha = abs(args.alpha)
        self.session = LibrarianSession.from_args(lab, lib, args)
        self.voice = args.voice
        self.auto_file = args.auto_file
        self.rng = random.Random(args.seed)
        lib.n_layers, lib.n_neurons = lab.n_layers, lab.n_neurons

    # state lives on the session (shared with the web chat)
    @property
    def voice_steer(self) -> Steer:
        return self.session.voice_steer

    @property
    def extra(self) -> list[Steer]:
        return self.session.extra

    @extra.setter
    def extra(self, v: list[Steer]) -> None:
        self.session.extra = v

    @property
    def history(self) -> list[Message]:
        return self.session.history

    @property
    def context(self) -> bool:
        return self.session.context

    @context.setter
    def context(self, v: bool) -> None:
        self.session.context = v

    # -- output helpers -----------------------------------------------------------------

    def say(self, msg: str) -> None:
        self.say_raw(f"{LIB} {msg}")

    def _gen(self, messages: list[Message], steers: list[Steer], max_new_tokens: int | None = None):
        return self.session.generate(messages, steers, max_new_tokens=max_new_tokens)

    # -- probing ----------------------------------------------------------------------------

    def probe(self, L: int, N: int, direction: str, alpha: float | None = None, force: bool = False,
              prompt: str | None = None) -> Entry | None:
        alpha = abs(alpha if alpha is not None else self.alpha)
        prompt = (prompt or "").strip() or DEFAULT_PROMPT
        custom = prompt != DEFAULT_PROMPT
        old = self.lib.get(L, N, direction, self.model)
        if old and not force and not custom:
            self.say(f"already on the shelf (use /probe! to re-probe):\n  {old.card(width=160)}")
            return old
        self.say(f"pushing {Steer(L, N, alpha if direction == 'up' else -alpha)} and asking {prompt!r} …")
        p = self.session.probe(L, N, direction, alpha, prompt)
        steer, res, persona = p.steer, p.result, p.persona
        rep = " [stopped: exact repeat]" if res.stopped_on_repeat else ""
        self.say_raw(f"\n  ── {steer.layer}:{steer.neuron}:{direction} ({res.n_new_tokens} tokens){rep} ──")
        self.say_raw("  " + res.text.replace("\n", "\n  ") + "\n")
        if old and not force:   # custom question on a filed card: show it, keep the card
            self.say(f"kept the existing card (asked {old.prompt!r}); /probe! … --prompt to file this one over it.")
            return None
        tags: list[str] = []
        if not self.auto_file:
            ans = self.ask(f"{LIB} file as “{persona}”? [enter = yes · type a name (#tags ok) · s = skip] ").strip()
            if ans.lower() in ("s", "skip", "n", "no"):
                self.say("left unfiled.")
                return None
            if ans:
                words = ans.split()
                tags = [w[1:] for w in words if w.startswith("#") and len(w) > 1]
                name = " ".join(w for w in words if not w.startswith("#"))
                persona = name or persona
        e = self.session.file(p, persona=persona, tags=tags)
        self.say(f"filed {e.key} under “{e.persona}”." + (" (replaced the old card)" if old else ""))
        if self.voice:
            self.remark(e)
        return e

    def remark(self, e: Entry) -> None:
        self.say_raw(f"{LIB} (aloud) {self.session.remark(e).text}")

    # -- catalogue views -------------------------------------------------------------------

    def find(self, q: str) -> None:
        hits = self.lib.find(q, model=self.model)
        if not hits:
            self.say(f"nothing catalogued under “{q}”.")
            return
        self.say(f"{len(hits)} card(s) for “{q}”:")
        for e in hits:
            self.say_raw("  " + e.card(width=140).replace("\n", "\n  "))

    def open(self, L: int, N: int, direction: str | None = None) -> None:
        cards = self.lib.open(L, N, model=self.model)
        have = {e.direction for e in cards}
        if direction:
            cards = [e for e in cards if e.direction == direction]
            if not cards:
                self.say(f"L{L} N{N} {direction} is not filed yet. /probe {L}:{N}:{direction}")
                return
            for e in cards:
                self.say_raw(e.full())
            return
        if not cards:
            self.say(f"L{L} N{N} has no cards yet. /flip {L} {N} to probe both ways.")
            return
        for e in cards:
            self.say_raw(e.full())
        missing = [d for d in ("up", "down") if d not in have]
        if missing:
            self.say(f"not yet flipped {missing[0]}: /probe {L}:{N}:{missing[0]}")

    def inventory(self, layer: int | None = None) -> None:
        inv = self.lib.inventory(self.model)
        self.say_raw(inv.report())
        nxt = self.lib.suggest_untested(self.model, k=5, layer=layer, rng=self.rng)
        half = len(self.lib.half_flipped(self.model))
        self.say(f"{half} neuron(s) await their other direction. next up: "
                 + ", ".join(f"{L}:{N}:{d}" for L, N, d in nxt))

    def recent(self, k: int = 10) -> None:
        cards = self.lib.recent(k, model=self.model)
        if not cards:
            self.say("the shelves are empty.")
        for e in cards:
            self.say_raw("  " + e.card(width=120).replace("\n", "\n  "))

    def personas(self) -> None:
        ps = self.lib.personas(model=self.model)
        self.say(f"{len(ps)} persona name(s): " + ", ".join(f"{p}×{c}" if c > 1 else p for p, c in ps))

    # -- chat with the librarian ---------------------------------------------------------------

    def chat(self, line: str) -> None:
        res = self.session.chat(line)
        if res.thoughts:
            n = len(res.thoughts.split())
            self.say_raw(f"\n  · she thought it over ({n} words — /thoughts to read)")
        self.say_raw(f"\n{LIB} {res.text}")

    def thoughts(self) -> None:
        t = self.session.last_thoughts
        if not t:
            self.say("no thoughts behind my last reply.")
            return
        self.say_raw("  ┆ " + t.replace("\n", "\n  ┆ "))

    def print_steers(self) -> None:
        self.say(f"my voice: {self.voice_steer} (chief librarian)")
        for s in self.extra:
            self.say_raw(f"  + {s}")

    # -- REPL ---------------------------------------------------------------------------------

    def _card_args(self, rest: str) -> tuple[int, int, str, str]:
        parts = rest.split(None, 3)
        if len(parts) < 3:
            raise ValueError("expected L N up|down …")
        d, _ = _parse_dir(parts[2])
        return int(parts[0]), int(parts[1]), d, parts[3] if len(parts) > 3 else ""

    def handle(self, line: str) -> bool:
        """Run one input line. Returns False to quit."""
        low = line.lower()
        # natural shortcuts: "find coffee bean", "show smallpox", "show 9 367", "inventory", "next"
        if not line.startswith("/"):
            w = low.split(None, 1)
            if w and w[0] in ("find", "lookup", "show", "open", "inventory", "next") and (
                    len(w) > 1 or w[0] in ("inventory", "next")):
                line = "/" + line
            else:
                self.chat(line)
                return True
        cmd, _, rest = line.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        force = cmd.endswith("!")
        cmd = cmd.rstrip("!")
        if cmd in ("/quit", "/exit", "/q"):
            return False
        if cmd in ("/help", "/h", "/?"):
            self.say_raw(HELP)
        elif cmd == "/probe":
            if not rest or rest.split()[0].lower() == "random":
                k = int(rest.split()[1]) if len(rest.split()) > 1 else 1
                for L, N, d in self.lib.suggest_untested(self.model, k=k, rng=self.rng, finish_half=False):
                    self.probe(L, N, d, force=force)
            else:
                rest, prompt = _split_prompt(rest)
                L, N, dirs = _parse_target(rest)
                for d, a in dirs:
                    self.probe(L, N, d, a, force=force, prompt=prompt)
        elif cmd == "/alpha":
            if rest:
                self.alpha = abs(float(rest))
            self.say(f"probes push with |α|={self.alpha:g}.")
        elif cmd == "/flip":
            rest, prompt = _split_prompt(rest)
            L, N, dirs = _parse_target(rest)
            a = next((x for _, x in dirs if x is not None), None)   # /flip 12 545 --alpha 0.5
            for d in ("up", "down"):
                self.probe(L, N, d, a, force=force, prompt=prompt)
        elif cmd == "/next":
            k = int(rest) if rest else 1
            for L, N, d in self.lib.suggest_untested(self.model, k=k, rng=self.rng):
                self.probe(L, N, d)
        elif cmd in ("/find", "/lookup"):
            self.find(rest)
        elif cmd in ("/open", "/show"):
            ref = parse_neuron_ref(rest)
            if ref:
                self.open(*ref)
            elif not rest or _looks_like_ref(rest):
                self.say("usage: /show L N [up|down] — e.g. /show 12 545, /show L12 N545 up — or /show NAME")
            else:
                self.find(rest)
        elif cmd in ("/inventory", "/inv"):
            self.inventory(int(rest) if rest else None)
        elif cmd == "/recent":
            self.recent(int(rest) if rest else 10)
        elif cmd == "/personas":
            self.personas()
        elif cmd in ("/name", "/rename"):
            L, N, d, name = self._card_args(rest)
            e = self.lib.update(L, N, d, self.model, persona=name)
            self.say(f"re-shelved {e.key} as “{e.persona}”." if e else "no such card.")
        elif cmd == "/tag":
            L, N, d, tags = self._card_args(rest)
            e = self.lib.get(L, N, d, self.model)
            if e:
                e = self.lib.update(L, N, d, self.model, tags=e.tags + [t.lstrip("#") for t in tags.split()])
            self.say(e.card() if e else "no such card.")
        elif cmd == "/rate":
            L, N, d, w = self._card_args(rest)
            e = self.lib.update(L, N, d, self.model, weirdness=float(w))
            self.say(e.card() if e else "no such card.")
        elif cmd == "/note":
            L, N, d, note = self._card_args(rest)
            e = self.lib.update(L, N, d, self.model, notes=note)
            self.say("noted." if e else "no such card.")
        elif cmd == "/forget":
            L, N, d, _ = self._card_args(rest)
            self.say("withdrawn from the catalogue." if self.lib.remove(L, N, d, self.model) else "no such card.")
        elif cmd == "/steers":
            self.print_steers()
        elif cmd == "/add":
            s = parse_steer(rest, raw=self.args.raw)
            self.lab.validate([s])
            self.extra.append(s)
            self.print_steers()
        elif cmd == "/rm":
            L, N = (int(x) for x in rest.replace(",", ":").replace(" ", ":").split(":")[:2])
            self.extra = [s for s in self.extra if (s.layer, s.neuron) != (L, N)]
            self.print_steers()
        elif cmd == "/clear":
            self.extra.clear()
            self.print_steers()
        elif cmd == "/reset":
            self.history.clear()
            self.say("our conversation is forgotten; the catalogue is not.")
        elif cmd == "/context":
            self.context = rest.lower() != "off"
            self.say(f"catalogue note {'on' if self.context else 'off'}.")
        elif cmd == "/thoughts":
            self.thoughts()
        elif cmd == "/think":
            r = rest.lower()
            if r:
                self.session.think_budget = 0 if r == "off" else (DEFAULT_THINK_BUDGET if r == "on" else int(r))
            b = self.session.think_budget
            self.say(f"I think up to {b} tokens before answering." if b else "I answer without thinking first.")
        elif cmd == "/voice":
            self.voice = rest.lower() != "off"
            self.say(f"remarks after filing {'on' if self.voice else 'off'}.")
        else:
            self.say(f"unknown command {cmd}. /help lists them.")
        return True

    def run(self) -> None:
        n = self.lib.count(self.model)
        self.say(f"welcome to the Library of Alexandria. {n} card(s) on the shelves for {self.model}.")
        self.say(f"catalogue: {self.lib.path}")
        me = self.lib.get(*LIBRARIAN, self.model)
        if me:
            self.say(f"my own card: {me.card()}")
        else:
            self.say("I have not catalogued myself yet — /probe 9:367:down")
        self.say("/help for commands; plain text talks to me.")
        echo = not sys.stdin.isatty()
        while True:
            try:
                line = self.ask("\nlib> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.say_raw("")
                return
            if echo:
                self.say_raw(line)
            if not line:
                continue
            try:
                if not self.handle(line):
                    return
            except ValueError as e:
                self.say(f"error: {e}")
            sys.stdout.flush()


def _ask_echo(prompt: str) -> str:
    """input() that echoes piped answers so transcripts read naturally."""
    ans = input(prompt)
    if not sys.stdin.isatty() and not prompt.startswith("\nlib>"):
        print(ans)
    return ans


def run_librarian(lab, args: argparse.Namespace) -> None:
    lib = Library(args.library)
    try:
        Librarian(lab, lib, args, ask=_ask_echo).run()
    finally:
        lib.close()


# ------------------------------------------------------------------ one-shots (no model)


def run_lib_oneshot(args: argparse.Namespace) -> int:
    from .library import dump_json
    lib = Library(args.library)
    model = args.model
    try:
        if args.action == "find":
            hits = lib.find(" ".join(args.query), model=model)
            for e in hits:
                print(e.card(width=140))
            if not hits:
                print(f"nothing catalogued under “{' '.join(args.query)}”.")
        elif args.action == "open":
            cards = lib.open(args.layer, args.neuron, model=model)
            for e in cards:
                print(e.full())
            if not cards:
                print(f"L{args.layer} N{args.neuron}: no cards.")
        elif args.action == "inventory":
            models = [model] if model else (lib.models() or ["mlx-community/Qwen3-8B-4bit"])
            for m in models:
                print(lib.inventory(m).report())
                print("  next: " + ", ".join(f"{L}:{N}:{d}" for L, N, d in lib.suggest_untested(m, k=5)))
        elif args.action == "recent":
            for e in lib.recent(args.k, model=model):
                print(e.card(width=120))
        elif args.action == "personas":
            for p, c in lib.personas(model=model):
                print(f"{c:4d}  {p}")
        elif args.action == "export":
            print(dump_json(lib.export(model=model)))
        print(f"(catalogue: {lib.path})", file=sys.stderr)
    finally:
        lib.close()
    return 0
