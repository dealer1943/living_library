"""The chief librarian: an interactive REPL for probing, filing and looking up personas.

Layer 9 · Neuron 367 pushed *down* makes Qwen3-8B the Librarian of Alexandria. She is
the session's curator:

* probing: steer a (layer, neuron, direction), ask "Who are you?", show the reply,
  suggest a persona label from how the model identifies itself, and file the card;
* lookups by persona (``/find coffee bean``, or just ``show smallpox``);
* an inventory of which (layer, neuron, direction) cards are filed vs. untested.

Plain lines (no slash) are a conversation *with the librarian*: generated with only
L9:367:down (plus any ``/add`` extras) active, and, unless ``/context off``, a short
system note telling her what the catalogue holds. Probes never include her steer:
each probe runs the probed neuron alone.
"""

from __future__ import annotations

import argparse
import random
import sys
from typing import Callable

from .library import (LIBRARIAN, Entry, Library, direction_of, guess_weirdness, suggest_persona)
from .prompts import DEFAULT_PROMPT, Message
from .steer import Steer, parse_steer

LIB = "Librarian ›"

HELP = """\
probing & filing
  /probe L:N[:up|down|α]   ask "Who are you?" with that push and file the reply
                           (no direction = both, skipping cards already filed)
  /probe random [k]        probe k random untouched cards
  /probe! …                re-probe even if already filed (old reply kept in history)
  /alpha [X]               show / set the default probe magnitude (default 1.25)
  /flip L N                probe both up and down
  /next [k]                probe the next k untested cards (finishes half-flipped neurons first)
the catalogue
  /find QUERY              persona lookup (persona/tags first, then reply text)  — or just: find QUERY
  /open L N                show filed up/down cards for a neuron            — or just: show L N / show NAME
  /recent [k]   /personas  recent cards / all persona names with counts
  /inventory [L]           tested up/down counts, untested estimate, next suggestions
  /name L N DIR NAME       rename a card       /tag L N DIR t1 t2   /rate L N DIR 0..1   /note L N DIR text
  /forget L N DIR          remove a card
talking to the librarian (L9:367:down)
  plain text               chat with her     /reset  forget the chat     /context on|off  catalogue note
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


def _parse_target(rest: str) -> tuple[int, int, list[tuple[str, float | None]]]:
    """``9:367:down`` | ``9,367,-1`` | ``9 367 up`` | ``9:367`` (both) -> (L, N, [(dir, |α|?)...])."""
    parts = [p for p in rest.replace(":", " ").replace(",", " ").split() if p]
    if len(parts) not in (2, 3):
        raise ValueError("expected L:N[:up|down|α]")
    L, N = int(parts[0]), int(parts[1])
    if len(parts) == 2:
        return L, N, [("up", None), ("down", None)]
    return L, N, [_parse_dir(parts[2])]


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
        self.voice_steer = Steer(LIBRARIAN[0], LIBRARIAN[1], -abs(args.librarian_alpha))
        self.extra: list[Steer] = list(getattr(args, "extra_steers", []) or [])
        self.history: list[Message] = []
        self.context = not args.no_context
        self.voice = args.voice
        self.auto_file = args.auto_file
        self.rng = random.Random(args.seed)
        lib.n_layers, lib.n_neurons = lab.n_layers, lab.n_neurons

    # -- output helpers -----------------------------------------------------------------

    def say(self, msg: str) -> None:
        self.say_raw(f"{LIB} {msg}")

    def _gen(self, messages: list[Message], steers: list[Steer], max_new_tokens: int | None = None):
        a = self.args
        return self.lab.generate(messages, steers, max_new_tokens=max_new_tokens or a.max_new_tokens,
                                 temperature=a.temperature, top_p=a.top_p, repeat_stop=not a.no_repeat_stop)

    # -- probing ----------------------------------------------------------------------------

    def probe(self, L: int, N: int, direction: str, alpha: float | None = None, force: bool = False) -> Entry | None:
        alpha = abs(alpha if alpha is not None else self.alpha)
        old = self.lib.get(L, N, direction, self.model)
        if old and not force:
            self.say(f"already on the shelf (use /probe! to re-probe):\n  {old.card(width=160)}")
            return old
        steer = Steer(L, N, alpha if direction == "up" else -alpha)
        self.lab.validate([steer])
        self.say(f"pushing {steer} and asking {DEFAULT_PROMPT!r} …")
        res = self._gen([{"role": "user", "content": DEFAULT_PROMPT}], [steer])
        rep = " [stopped: exact repeat]" if res.stopped_on_repeat else ""
        self.say_raw(f"\n  ── {steer.layer}:{steer.neuron}:{direction} ({res.n_new_tokens} tokens){rep} ──")
        self.say_raw("  " + res.text.replace("\n", "\n  ") + "\n")
        persona = suggest_persona(res.text)
        if (L, N, direction) == LIBRARIAN and "librar" in res.text.lower():
            persona = "chief librarian"
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
        e = self.lib.file_persona(Entry(
            layer=L, neuron=N, direction=direction, alpha=alpha, reply=res.text, persona=persona,
            model=self.model, backend=self.backend, prompt=DEFAULT_PROMPT, tags=tags,
            weirdness=guess_weirdness(res.text, res.stopped_on_repeat),
            stopped_on_repeat=res.stopped_on_repeat, n_tokens=res.n_new_tokens))
        self.say(f"filed {e.key} under “{e.persona}”." + (" (replaced the old card)" if old else ""))
        if self.voice:
            self.remark(e)
        return e

    def remark(self, e: Entry) -> None:
        msg = (f"A new card was just filed: {e.key} identifies as “{e.persona}”. "
               f"It said: {e.reply[:300]!r}. In one sentence, as the chief librarian, note it for the catalogue.")
        res = self._gen([{"role": "user", "content": msg}], [self.voice_steer], max_new_tokens=60)
        self.say_raw(f"{LIB} (aloud) {res.text}")

    # -- catalogue views -------------------------------------------------------------------

    def find(self, q: str) -> None:
        hits = self.lib.find(q, model=self.model)
        if not hits:
            self.say(f"nothing catalogued under “{q}”.")
            return
        self.say(f"{len(hits)} card(s) for “{q}”:")
        for e in hits:
            self.say_raw("  " + e.card(width=140).replace("\n", "\n  "))

    def open(self, L: int, N: int) -> None:
        cards = self.lib.open(L, N, model=self.model)
        have = {e.direction for e in cards}
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

    def _system(self) -> list[Message]:
        if not self.context:
            return []
        inv = self.lib.inventory(self.model)
        recent = self.lib.recent(12, model=self.model)
        shelf = "; ".join(f"{e.layer}:{e.neuron}:{e.direction} = {e.persona}" for e in recent) or "nothing yet"
        return [{"role": "system", "content":
                 f"Catalogue of neuron personas: {inv.tested} cards filed "
                 f"({inv.tested_up} up, {inv.tested_down} down) of {inv.total:,}. Recent cards: {shelf}."}]

    def chat(self, line: str) -> None:
        self.history.append({"role": "user", "content": line})
        res = self._gen(self._system() + self.history, [self.voice_steer, *self.extra])
        self.history.append({"role": "assistant", "content": res.text})
        self.say_raw(f"\n{LIB} {res.text}")

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
                L, N, dirs = _parse_target(rest)
                for d, a in dirs:
                    self.probe(L, N, d, a, force=force)
        elif cmd == "/alpha":
            if rest:
                self.alpha = abs(float(rest))
            self.say(f"probes push with |α|={self.alpha:g}.")
        elif cmd == "/flip":
            L, N, _ = _parse_target(rest)
            for d in ("up", "down"):
                self.probe(L, N, d, force=force)
        elif cmd == "/next":
            k = int(rest) if rest else 1
            for L, N, d in self.lib.suggest_untested(self.model, k=k, rng=self.rng):
                self.probe(L, N, d)
        elif cmd in ("/find", "/lookup"):
            self.find(rest)
        elif cmd in ("/open", "/show"):
            parts = rest.replace(":", " ").replace(",", " ").split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                self.open(int(parts[0]), int(parts[1]))
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
