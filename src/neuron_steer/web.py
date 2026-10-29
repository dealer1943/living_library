"""Web chat with the chief librarian (``neuron-steer serve`` / ``neuron-steer web``).

A small FastAPI app serving one static chat page plus a JSON API:

* ``POST /api/chat``         {message, session_id?, history?} -> her ``reply`` (L9:367:down + extras)
                             and, apart from it, her private ``thoughts``
* ``POST /api/chat/stream``  same body, Server-Sent Events: ``thought`` pieces (her <think> block),
                             ``reply`` (the cleaned spoken reply so far, replaces), ``spill`` (untagged
                             reasoning split off the reply so far, replaces), then ``done``
* ``POST /api/reset``        {session_id} -> forget that conversation
* ``POST /api/probe``        {layer, neuron, direction?, alpha?, prompt?, force?, file?, persona?, tags?} |
                             {spec: "12:545 --alpha 0.5 --prompt \"what is your story?\"", ...}
                             (prompt defaults to "Who are you?"; a custom prompt on an already-filed
                             card returns the reply unfiled unless force)
* ``GET  /api/inventory``, ``/api/find?q=``, ``/api/open?layer=&neuron=``, ``/api/recent?k=``
  catalogue reads straight from SQLite (no model needed)
* ``GET  /api/health``       model loaded? which steers?
* ``POST /api/about/stream``  F00015 About room: {message, history?, model?: qwen3-8b|bonsai-27b,
                             continue_text?} -> the librarian teaching from docs/neuron_primer.md (SSE)
* ``GET  /api/models``, ``POST /api/models/start|stop`` {id}  teachers for the About room

The model loads once, on a single dedicated worker thread, and every generation runs on
that same thread: MLX streams are per-thread and the steering hooks mutate the model, so
model calls are serialised there. Chat state is :class:`~neuron_steer.librarian.LibrarianSession`,
the same class the terminal REPL uses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import about as about_mod
from .library import DEFAULT_DB, LIBRARIAN, Entry, Library
from .librarian import _ALPHA_FLAG, LibrarianSession, _parse_dir, _parse_target, _split_prompt
from .personas import keyword_request, normalize_keywords, persona_messages, is_echo, pick_keywords, strip_speaker, trim_repeats
from .prompts import DEFAULT_PROMPT, split_live
from .steer import Steer

STATIC = Path(__file__).parent / "static"
MAX_SESSIONS = 64
DEFAULT_PORT = 8765


def _db_path(args: argparse.Namespace) -> Path:
    return Path(args.library or os.environ.get("NEURON_LIBRARY") or DEFAULT_DB)


def _entry(e: Entry) -> dict:
    d = asdict(e)
    d["key"] = e.key
    d["card"] = e.card()
    d["is_librarian"] = e.is_librarian
    return d


def _continuation(res) -> dict:
    """A continuation's reply + the whitespace joining it to the part before (for merging)."""
    raw = res.text
    body = raw.lstrip()
    return {"reply": trim_repeats(body).strip() if body else "", "joiner": raw[:len(raw) - len(body)],
            "continued": True, "truncated": res.truncated, "thoughts": "", "n_tokens": res.n_new_tokens,
            "stopped_on_repeat": res.stopped_on_repeat}


def _steer(s) -> dict:
    return {"layer": s.layer, "neuron": s.neuron, "alpha": s.alpha, "raw": s.raw, "label": str(s)}


# ------------------------------------------------------------------ targets: "12:545:up 7:271 --mix", "smallpox + emily"

_SPEC_TOKEN = re.compile(r"^L?\d{1,2}[:,]N?\d{1,5}(?:[:,](?:up|down|u|d|\+|-|[+-]?(?:\d+(?:\.\d*)?|\.\d+)))*$", re.I)
_MIX_FLAG = re.compile(r"(?:^|\s)--mix(?=\s|$)", re.I)
DEFAULT_CHAT_ALPHA = 1.0
CHAT_ALPHA_CAP = 1.0  # emily (filed at 1.25) drifts into puzzle-solving above ~1.0 in multi-turn chat
N_LAYERS_MAX, N_NEURONS_MAX = 36, 12288


def _member(lib: Library, model: str, L: int, N: int, direction: str, alpha: float | None,
            default_alpha: float, entry: Entry | None = None) -> dict:
    if not (0 <= L < N_LAYERS_MAX and 0 <= N < N_NEURONS_MAX):
        raise ValueError(f"L{L} N{N} is outside the model (layers 0–{N_LAYERS_MAX - 1}, neurons 0–{N_NEURONS_MAX - 1})")
    e = entry or lib.get(L, N, direction, model)
    a = abs(alpha) if alpha is not None else (min(abs(e.alpha), CHAT_ALPHA_CAP) if e else default_alpha)
    persona = e.persona if e and e.persona and not e.persona.startswith("?") else None
    return {"layer": L, "neuron": N, "direction": direction, "alpha": a, "signed": a if direction == "up" else -a,
            "persona": persona, "filed": bool(e), "tags": e.tags if e else [],
            "label": f"L{L} N{N} {direction}", "name": persona or f"L{L} N{N} {direction}",
            "explicit_alpha": alpha is not None}


def resolve_spec(spec: str, lib: Library, model: str, default_alpha: float = DEFAULT_CHAT_ALPHA) -> dict:
    """Parse checkout / librarian targets -> {mix, members:[…]} (catalogue lookups, no model).

    ``12:545:up`` | ``12:545:up:0.6`` | ``L12 N545 up`` | ``9:367`` (direction: the filed one, else up) |
    several colon specs ``12:545:up 7:271:down`` | persona names joined with ``+`` (``smallpox + emily``) |
    ``--mix`` | ``--alpha X`` (|α| for members without their own).
    """
    spec = str(spec or "").strip()
    mix = bool(_MIX_FLAG.search(spec))
    spec = _MIX_FLAG.sub(" ", spec)
    flag = None
    m = _ALPHA_FLAG.search(spec)
    if m:
        flag = abs(float(m.group(1)))
        spec = (spec[:m.start()] + " " + spec[m.end():]).strip()
    if not spec:
        raise ValueError("name at least one neuron: 12:545:up, L12 N545 up, or a filed persona name")
    members: list[dict] = []
    for group in re.split(r"\s+\+\s+|\s*;\s*", spec):
        group = group.strip()
        if not group:
            continue
        toks = group.split()
        targets = None
        if all(_SPEC_TOKEN.match(t) for t in toks):
            targets = [_parse_target(t) for t in toks]
        else:
            try:
                targets = [_parse_target(group)]
            except ValueError:
                targets = None
        if targets is None:   # a persona name
            hits = lib.find(group, model=model, in_reply=False, limit=5) or lib.find(group, model=model, limit=5)
            if not hits:
                raise ValueError(f"no filed persona matches “{group}” — use L:N:up|down, or /find {group}")
            e = hits[0]
            members.append(_member(lib, model, e.layer, e.neuron, e.direction, flag, default_alpha, e))
            continue
        for L, N, dirs in targets:
            if len(dirs) == 2:   # no direction given: the filed one if only one is, else up
                filed = [d for d in ("up", "down") if lib.get(L, N, d, model)]
                d, a = (filed[0] if len(filed) == 1 else "up"), dirs[0][1]
            else:
                d, a = dirs[0]
            members.append(_member(lib, model, L, N, d, a if a is not None else flag, default_alpha))
    seen, uniq = set(), []
    for mb in members:
        k = (mb["layer"], mb["neuron"], mb["direction"])
        if k not in seen:
            seen.add(k)
            uniq.append(mb)
    return {"mix": mix, "members": uniq}


class LibrarianServer:
    """Owns the model thread, the shared LibrarianSession template and per-browser sessions."""

    def __init__(self, args: argparse.Namespace, load_model: bool = True):
        self.args = args
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="librarian-model")
        # F00015: the 27B teacher is an HTTP call to llama-server, so it never queues behind the 8B
        self.http_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="about-http")
        self.bonsai = about_mod.Bonsai(getattr(args, "bonsai_url", None) or about_mod.DEFAULT_BONSAI_URL,
                                       getattr(args, "bonsai_dir", None))
        self._cards: list | None = None
        self._cards_mtime = 0.0
        self.base: LibrarianSession | None = None
        self.sessions: OrderedDict[str, LibrarianSession] = OrderedDict()
        self.ready = threading.Event()
        self.error: str | None = None if load_model else "server started with --no-model"
        if load_model:
            self.pool.submit(self._load)

    # -- model thread ---------------------------------------------------------------------

    def _load(self) -> None:
        from .cli import _load
        try:
            lab = _load(self.args)
            lib = Library(self.args.library)  # this connection lives on the model thread
            lib.n_layers, lib.n_neurons = lab.n_layers, lab.n_neurons
            self.base = LibrarianSession.from_args(lab, lib, self.args)
            self.ready.set()
            print("model ready — the Librarian will see you now.", file=sys.stderr)
        except Exception as e:  # surfaced via /api/health and chat errors
            self.error = f"{type(e).__name__}: {e}"
            print(f"model load failed: {self.error}", file=sys.stderr)

    def _session(self, sid: str | None, history: list[dict] | None) -> tuple[str, LibrarianSession]:
        if self.base is None:
            raise RuntimeError(self.error or "model not loaded")
        sid = sid or uuid.uuid4().hex
        s = self.sessions.get(sid)
        if s is None:
            s = self.base.fork()
            self.sessions[sid] = s
            while len(self.sessions) > MAX_SESSIONS:
                self.sessions.popitem(last=False)
        self.sessions.move_to_end(sid)
        if history is not None:
            s.history[:] = [{"role": m["role"], "content": str(m["content"])} for m in history
                            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and "content" in m]
        return sid, s

    def chat_sync(self, body: dict, on_text=None, on_thought=None) -> dict:
        msg = str(body.get("message") or "").strip()
        cont = str(body.get("continue_text") or "")
        if not msg and not cont:
            raise ValueError("empty message")
        sid, s = self._session(body.get("session_id"), body.get("history"))
        v = body.get("voice")   # F00006: the page chooses who is behind the desk (none = L9 N367 down)
        if isinstance(v, dict) and v.get("layer") is not None:
            a = float(v.get("alpha", 0.4))
            if str(v.get("direction") or "").lower() in ("up", "down"):
                a = abs(a) if v["direction"].lower() == "up" else -abs(a)
            s.set_voice(Steer(int(v["layer"]), int(v["neuron"]), a), v.get("name"))
        else:
            s.set_voice(None)
        if cont:   # carry on a reply cut at the token limit: history ends with the user's turn
            if not s.history or s.history[-1]["role"] != "user":
                raise ValueError("continue: history must end with the user's message")
            res = s.generate(s.system() + s.history, s.steers, on_text=on_text, assistant_prefix=cont)
            return {"session_id": sid, **_continuation(res), "steers": [_steer(x) for x in s.steers]}
        res = s.chat(msg, on_text=on_text, on_thought=on_thought)
        return {"session_id": sid, "reply": res.text, "truncated": res.truncated, "thoughts": res.thoughts, "n_tokens": res.n_new_tokens,
                "stopped_on_repeat": res.stopped_on_repeat, "turns": len(s.history) // 2,
                "steers": [_steer(x) for x in s.steers],
                "applied": [str(a) for a in res.applied]}

    # -- F00015: the About room ------------------------------------------------------------

    def cards(self) -> list:
        """Primer cards, re-read when docs/neuron_primer.md changes (edit it without a restart)."""
        path = Path(getattr(self.args, "primer", None) or about_mod.PRIMER)
        m = path.stat().st_mtime
        if self._cards is None or m != self._cards_mtime:
            self._cards, self._cards_mtime = about_mod.load_cards(path), m
        return self._cards

    def about_model(self, body: dict) -> str:
        mid = str(body.get("model") or getattr(self.args, "about_model", None) or about_mod.DEFAULT_ABOUT_MODEL)
        if mid not in about_mod.MODEL_IDS:
            raise ValueError(f"unknown model {mid!r}; pick one of {sorted(about_mod.MODEL_IDS)}")
        return mid

    def about_sync(self, body: dict, on_text=None, on_thought=None) -> dict:
        """One teaching turn. The system prompt is rebuilt every turn from the primer cards that match
        this question (and the one before it, for follow-ups like "and down?")."""
        msg = str(body.get("message") or "").strip()
        cont = str(body.get("continue_text") or "")
        history = about_mod.clean_history(body.get("history"))
        if msg and not cont:
            history.append({"role": "user", "content": msg})
        if not history or history[-1]["role"] != "user":
            raise ValueError("empty message")
        mid = self.about_model(body)
        users = [m["content"] for m in history if m["role"] == "user"][-2:]
        system, picked = about_mod.teach_system(self.cards(), " ".join(users), steered=(mid == "qwen3-8b"))
        msgs = [{"role": "system", "content": system}, *history]
        max_new = int(body.get("max_new_tokens") or getattr(self.args, "about_max_tokens", 600))
        if mid == "bonsai-27b":
            if cont:
                msgs.append({"role": "assistant", "content": cont})
            r = self.bonsai.chat(msgs, on_text=on_text, on_thought=on_thought, max_tokens=max_new,
                                 thinking=bool(body.get("thinking", False)))
            reply = r["text"].lstrip() if cont else r["text"].strip()
            from .prompts import split_thoughts
            tagged, reply = split_thoughts(reply) if not cont else ("", reply)
            out = {"reply": reply, "thoughts": "\n\n".join(x for x in (r["thoughts"], tagged) if x.strip()),
                   "truncated": r["truncated"], "n_tokens": r["n_tokens"]}
            if cont:
                body_text = r["text"].lstrip()
                out.update(reply=body_text.strip(), joiner=r["text"][:len(r["text"]) - len(body_text)],
                           continued=True, thoughts="")
            return {**out, "model": mid, "cards": picked, "steers": []}
        if self.base is None:
            raise RuntimeError(self.error or "model not loaded")
        s = self.base
        voice = s.default_voice
        va = body.get("voice_alpha", getattr(self.args, "about_alpha", None))   # her push while teaching
        if va is not None:
            voice = Steer(voice.layer, voice.neuron, -abs(float(va)))
        steers = [voice] if voice.alpha else []   # voice_alpha 0 = plain Qwen3-8B
        if cont:
            res = s.generate(msgs, steers, max_new_tokens=max_new, on_text=on_text, assistant_prefix=cont)
            return {**_continuation(res), "model": mid, "cards": picked, "steers": [_steer(x) for x in steers]}
        from .librarian import _separate
        res = _separate(s.generate(msgs, steers, max_new_tokens=max_new,
                                   think_budget=int(getattr(self.args, "think_budget", 0) or 0),
                                   on_text=on_text, on_thought=on_thought))
        spill, reply = split_live(res.text)
        thoughts = "\n\n".join(x for x in (res.thoughts, spill) if x.strip())
        reply = trim_repeats(reply).strip()
        return {"reply": reply or "(only thoughts this turn — open Thoughts above, or ask again.)", "no_reply": not reply,
                "thoughts": thoughts, "truncated": bool(reply) and res.truncated, "n_tokens": res.n_new_tokens,
                "stopped_on_repeat": res.stopped_on_repeat, "model": mid, "cards": picked,
                "steers": [_steer(x) for x in steers]}

    def models_info(self) -> dict:
        b = self.bonsai.status()
        out = []
        for m in about_mod.MODELS:
            d = dict(m)
            if m["id"] == "qwen3-8b":
                d.update(lab_model=self.args.model, ready=self.ready.is_set(), error=self.error, state=(
                    "ok" if self.ready.is_set() else ("error" if self.error else "loading")))
            else:
                d.update(ready=b["state"] == "ok", **b)
            out.append(d)
        return {"lab_model": self.args.model, "about_default": getattr(self.args, "about_model", None)
                or about_mod.DEFAULT_ABOUT_MODEL, "models": out}

    def reset_sync(self, sid: str | None) -> dict:
        if sid and sid in self.sessions:
            self.sessions[sid].reset()
        return {"session_id": sid, "reset": True}

    def probe_sync(self, body: dict) -> dict:
        if self.base is None:
            raise RuntimeError(self.error or "model not loaded")
        s = self.base
        alpha = body.get("alpha")
        prompt = body.get("prompt")
        if body.get("spec"):   # the slash-command text after /probe, parsed like the REPL
            spec, spec_prompt = _split_prompt(str(body["spec"]))
            prompt = prompt or spec_prompt
            L, N, dirs = _parse_target(spec)
        else:
            L, N = int(body["layer"]), int(body["neuron"])
            d = str(body.get("direction") or "both").lower()
            dirs = [("up", None), ("down", None)] if d == "both" else [_parse_dir(d)]
        prompt = str(prompt or "").strip() or DEFAULT_PROMPT
        custom = prompt != DEFAULT_PROMPT
        force, do_file = bool(body.get("force")), body.get("file", True)
        out = []
        for direction, a in dirs:
            a = abs(float(alpha if alpha is not None else (a if a is not None else self.args.alpha)))
            old = s.lib.get(L, N, direction, s.model)
            if old and not force and not custom:
                out.append({"status": "already filed", "entry": _entry(old)})
                continue
            p = s.probe(L, N, direction, a, prompt)
            item: dict[str, Any] = {"layer": L, "neuron": N, "direction": direction, "alpha": a, "prompt": p.prompt,
                                    "reply": p.result.text, "suggested_persona": p.persona,
                                    "steer": _steer(p.steer)}
            if old and not force:   # custom question on a filed card: show it, keep the card
                item["status"] = "unfiled (card kept; /probe! to file)"
            elif do_file:
                e = s.file(p, persona=body.get("persona") or None, tags=body.get("tags") or [])
                item.update(status="replaced" if old else "filed", entry=_entry(e))
            else:
                item["status"] = "unfiled"
            out.append(item)
        return {"results": out}

    # -- checked-out personas (F00003–F00005) ------------------------------------------------

    def _steers(self, members: list[dict]) -> list[Steer]:
        if not members:
            raise ValueError("no members")
        out = []
        for m in members:
            a = abs(float(m.get("alpha", 1.0)))
            d = str(m.get("direction") or "up").lower()
            out.append(Steer(int(m["layer"]), int(m["neuron"]), a if d == "up" else -a))
        return out

    NO_REPLY = ("(only thoughts this turn — no spoken reply. Open Thoughts above, ask again, "
                "or ease the push: /alpha 0.6)")
    NUDGE = "(Answer me directly, in your own voice, in one to three sentences. Do not narrate your reasoning.)"

    def persona_sync(self, body: dict, on_text=None, on_thought=None) -> dict:
        """One reply in a persona tab. mode single|mix: every member pushed at once, one voice;
        mode group: only ``members[speaker]`` speaks, seeing the whole shared transcript.

        Same leak guard as the librarian: Qwen3 thinks inside <think>…</think> (streamed as
        ``thought``), only the cleaned spoken reply is streamed/returned, and untagged reasoning
        ("Okay, I'm going to try to figure out what the user…") is moved to the thoughts. A turn
        that is reasoning all the way down gets one nudged retry; it is never shown as the reply."""
        if self.base is None:
            raise RuntimeError(self.error or "model not loaded")
        s = self.base
        members = list(body.get("members") or [])
        mode = str(body.get("mode") or ("mix" if len(members) > 1 else "single"))
        transcript = [t for t in (body.get("transcript") or []) if isinstance(t, dict)]
        me = None
        if mode == "group":
            i = int(body.get("speaker", 0))
            steers = self._steers([members[i]])
            names = [str(m.get("name") or f"L{m['layer']} N{m['neuron']}") for m in members]
            me = names[i]
            msgs = persona_messages(transcript, me, group=names)
            max_new = int(body.get("max_new_tokens") or 200)
        else:
            steers = self._steers(members)
            msgs = persona_messages(transcript, str(body.get("name") or "persona"))
            max_new = int(body.get("max_new_tokens") or s.max_new_tokens)
        if not msgs or msgs[-1]["role"] != "user":
            raise ValueError("the transcript must end with a message to the persona")
        self.base.lab.validate(steers)
        from .librarian import _separate
        if body.get("continue_text"):   # carry on a reply cut at the token limit
            res = s.generate(msgs, steers, max_new_tokens=max_new, on_text=on_text,
                             assistant_prefix=str(body["continue_text"]))
            return {**_continuation(res), "mode": mode, "steers": [_steer(x) for x in steers], "speaker": body.get("speaker")}
        # thinking stays off for personas: a steered voice given a <think> channel loops in it and keeps
        # reasoning into the reply (tested: emily 12:545:up, L11 N111 up). Any <think> it emits anyway, and
        # untagged reasoning, is still split off by _separate / split_live below.
        budget = int(body.get("think_budget") or 0)

        def once(messages, stream: bool):
            res = _separate(s.generate(messages, steers, max_new_tokens=max_new, think_budget=budget,
                                       on_text=on_text if stream else None,
                                       on_thought=on_thought if stream else None))
            text = strip_speaker(res.text, me) if me else res.text
            spill, reply = split_live(text)   # untagged reasoning left in the reply -> thoughts
            thoughts = "\n\n".join(x for x in (res.thoughts, spill) if x.strip())
            return res, trim_repeats(reply).strip(), thoughts

        res, reply, thoughts = once(msgs, True)
        if reply and is_echo(reply, transcript):   # parroted the room / your question: one more try
            res, reply, thoughts = once(msgs, False)
        retried = False
        if not reply:   # all thinking, nothing said: nudge once (not streamed; the bubble keeps its thoughts)
            retried = True
            nudged = [*msgs[:-1], {"role": "user", "content": msgs[-1]["content"] + "\n\n" + self.NUDGE}]
            res2, reply, thoughts2 = once(nudged, False)
            if reply and is_echo(reply, transcript):
                reply = ""
            thoughts = "\n\n".join(x for x in (thoughts, thoughts2) if x.strip())
            res = res2
        return {"reply": reply or self.NO_REPLY, "no_reply": not reply, "retried": retried,
                "truncated": bool(reply) and res.truncated,
                "thoughts": thoughts, "n_tokens": res.n_new_tokens, "mode": mode,
                "stopped_on_repeat": res.stopped_on_repeat, "steers": [_steer(x) for x in steers],
                "speaker": body.get("speaker")}

    def checkin_sync(self, body: dict) -> dict:
        """Check a tab back in: five keywords (yours, or the librarian's reading of the chat), logged
        per member in the catalogue and merged into filed cards' tags."""
        members = list(body.get("members") or [])
        if not members:
            raise ValueError("nothing to check in")
        transcript = [t for t in (body.get("transcript") or []) if isinstance(t, dict)]
        name = str(body.get("name") or "persona")
        text = "\n".join(str(t.get("content") or "") for t in transcript if t.get("speaker") != "user")
        kws, source, answer = normalize_keywords(str(body.get("keywords") or ""), k=5), "user", ""
        if not kws:
            source = "librarian"
            if self.base is not None:
                s = self.base
                res = s.generate(keyword_request(name, transcript), [s.default_voice], max_new_tokens=24)
                from .librarian import _separate
                answer = _separate(res).text
            names = re.findall(r"[a-z][a-z'-]+", " ".join([name, *(str(m.get("name") or "") for m in members)]).lower())
            kws = pick_keywords(answer, text or name, exclude=names)
        lib = self.base.lib if self.base is not None else Library(self.args.library)
        try:
            ids = [lib.log_checkin(int(m["layer"]), int(m["neuron"]), str(m["direction"]), float(m.get("alpha", 1.0)),
                                   self.args.model, kws, source=source, mode=str(body.get("mode") or "single"),
                                   group_name=name if len(members) > 1 else "",
                                   turns=sum(1 for t in transcript if t.get("speaker") == "user"),
                                   checked_out_at=body.get("checked_out_at"))
                   for m in members]
            tagged = [f"L{m['layer']} N{m['neuron']} {m['direction']}" for m in members
                      if lib.get(int(m["layer"]), int(m["neuron"]), str(m["direction"]), self.args.model)]
        finally:
            if self.base is None:
                lib.close()
        return {"keywords": kws, "source": source, "librarian_said": answer, "logged": ids, "tagged": tagged}

    async def run(self, fn, *a, **kw):
        return await asyncio.get_running_loop().run_in_executor(self.pool, lambda: fn(*a, **kw))


def create_app(args: argparse.Namespace, load_model: bool = True):
    from fastapi import Body, FastAPI, HTTPException
    from fastapi.responses import FileResponse, StreamingResponse

    srv = LibrarianServer(args, load_model=load_model)
    app = FastAPI(title="Librarian of Alexandria", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.librarian = srv

    def lib_model(model: str | None) -> str | None:
        if model in ("*", "all"):
            return None
        return model or args.model

    def open_lib() -> Library:
        return Library(args.library)

    async def guarded(fn, *a):
        try:
            return await srv.run(fn, *a)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(503, str(e))

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})  # never a stale page

    @app.get("/api/health")
    async def health():   # on the event loop: never queues behind the model thread or the threadpool
        L, N, d = LIBRARIAN
        return {"ready": srv.ready.is_set(), "error": srv.error, "model": args.model, "backend": args.backend,
                "librarian": {"layer": L, "neuron": N, "direction": d, "alpha": -abs(args.librarian_alpha)},
                "extra_steers": [_steer(s) for s in getattr(args, "extra_steers", [])],
                "probe_alpha": args.alpha, "context": not args.no_context,
                "think_budget": getattr(args, "think_budget", 0),
                "catalogue": str(_db_path(args)),
                "about": {"default_model": getattr(args, "about_model", None) or about_mod.DEFAULT_ABOUT_MODEL,
                          "models": [m["id"] for m in about_mod.MODELS]}}

    @app.post("/api/chat")
    async def chat(body: dict = Body(...)):
        return await guarded(srv.chat_sync, body)

    @app.post("/api/chat/stream")
    async def chat_stream(body: dict = Body(...)):
        return sse(lambda on_text, on_thought: srv.chat_sync(body, on_text=on_text, on_thought=on_thought),
                   raw_reply=bool(body.get("continue_text")))

    @app.post("/api/about/stream")
    async def about_stream(body: dict = Body(...)):
        """F00015: the About room — the librarian teaches from docs/neuron_primer.md."""
        try:
            mid = srv.about_model(body)
        except ValueError as e:
            raise HTTPException(400, str(e))
        cont = bool(body.get("continue_text"))
        if mid == "bonsai-27b":   # plain HTTP to llama-server: its own pool, its own reply cleaning
            return sse(lambda on_text, on_thought: srv.about_sync(body, on_text=on_text, on_thought=on_thought),
                       raw_reply=True, pool=srv.http_pool)
        return sse(lambda on_text, on_thought: srv.about_sync(body, on_text=on_text, on_thought=on_thought),
                   raw_reply=cont)

    @app.get("/api/models")
    async def models():
        return await asyncio.to_thread(srv.models_info)

    @app.post("/api/models/start")
    async def models_start(body: dict = Body(default={})):
        if str(body.get("id") or "bonsai-27b") != "bonsai-27b":
            raise HTTPException(400, "only bonsai-27b is started on demand (the 8B lab loads with the server)")
        try:
            return await asyncio.to_thread(srv.bonsai.start)
        except RuntimeError as e:
            raise HTTPException(503, str(e))

    @app.post("/api/models/stop")
    async def models_stop(body: dict = Body(default={})):
        return await asyncio.to_thread(srv.bonsai.stop)

    @app.post("/api/persona/stream")
    async def persona_stream(body: dict = Body(...)):
        """F00003–F00005: a checked-out persona's reply (single, --mix blend, or one group member)."""
        return sse(lambda on_text, on_thought: srv.persona_sync(body, on_text=on_text, on_thought=on_thought),
                   raw_reply=bool(body.get("continue_text")))

    @app.post("/api/checkin")
    async def checkin(body: dict = Body(...)):
        return await guarded(srv.checkin_sync, body)

    @app.get("/api/checkins")
    def checkins(limit: int = 50):
        lib = open_lib()
        try:
            return {"results": lib.checkins(model=args.model, limit=limit)}
        finally:
            lib.close()

    def sse(work, raw_reply: bool = False, pool=None):
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        # Her reply is streamed as the *cleaned* reply-so-far ("reply" events replace the bubble
        # text), with untagged reasoning ("Okay, the user is asking…", "Wait, …") routed to the
        # thoughts ("spill" events replace the loose-thought text). Raw deltas used to go straight
        # into the bubble, so reasoning flashed in the chat and vanished when "done" cleaned it.
        raw: list[str] = []
        last = {"reply": None, "spill": None}

        def on_text(t: str) -> None:
            raw.append(t)
            spill, reply = ("", "".join(raw).lstrip()) if raw_reply else split_live("".join(raw))
            for kind, val in (("spill", spill), ("reply", reply)):
                if val != last[kind]:
                    last[kind] = val
                    loop.call_soon_threadsafe(q.put_nowait, {"type": kind, "text": val})

        def on_thought(t: str) -> None:
            loop.call_soon_threadsafe(q.put_nowait, {"type": "thought", "text": t})

        def job() -> None:
            try:
                r = work(on_text, on_thought)
                loop.call_soon_threadsafe(q.put_nowait, {"type": "done", **r})
            except Exception as e:  # noqa: BLE001 - reported to the client
                loop.call_soon_threadsafe(q.put_nowait, {"type": "error", "error": str(e)})

        (pool or srv.pool).submit(job)

        async def events():
            yield f"data: {json.dumps({'type': 'queued', 'ready': srv.ready.is_set() or pool is not None})}\n\n"
            while True:
                ev = await q.get()
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev["type"] in ("done", "error"):
                    return

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/reset")
    async def reset(body: dict = Body(default={})):
        return await srv.run(srv.reset_sync, body.get("session_id"))

    @app.post("/api/probe")
    async def probe(body: dict = Body(...)):
        return await guarded(srv.probe_sync, body)

    @app.post("/api/resolve")
    def resolve(body: dict = Body(...)):
        """Targets for /checkout and /librarian: {spec, default_alpha?} -> {mix, members}."""
        lib = open_lib()
        try:
            r = resolve_spec(str(body.get("spec") or ""), lib, args.model,
                             float(body.get("default_alpha") or DEFAULT_CHAT_ALPHA))
            if body.get("card_alpha") is False:   # /librarian: chat α, not the card's probe α, unless given
                for mb in r["members"]:
                    if not mb.get("explicit_alpha"):
                        a = float(body.get("default_alpha") or DEFAULT_CHAT_ALPHA)
                        mb.update(alpha=a, signed=a if mb["direction"] == "up" else -a)
            return r
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            lib.close()

    @app.get("/api/inventory")
    def inventory(model: str | None = None, layer: int | None = None, k: int = 5):
        lib = open_lib()
        try:
            models = [lib_model(model)] if lib_model(model) else (lib.models() or [args.model])
            out = []
            for m in models:
                inv = lib.inventory(m)
                out.append({"model": m, "total": inv.total, "tested": inv.tested, "tested_up": inv.tested_up,
                            "tested_down": inv.tested_down, "untested": inv.untested,
                            "both": inv.both, "one_way": inv.one_way,
                            "per_layer": {str(L): {"up": u, "down": d} for L, (u, d) in sorted(inv.per_layer.items())},
                            "next": [f"{L}:{N}:{d}" for L, N, d in lib.suggest_untested(m, k=k, layer=layer)],
                            "report": inv.report()})
            return {"catalogue": str(lib.path), "inventories": out}
        finally:
            lib.close()

    @app.get("/api/find")
    def find(q: str, model: str | None = None, limit: int = 50):
        lib = open_lib()
        try:
            return {"q": q, "results": [_entry(e) for e in lib.find(q, model=lib_model(model), limit=limit)]}
        finally:
            lib.close()

    @app.get("/api/open")
    def open_neuron(layer: int, neuron: int, model: str | None = None):
        lib = open_lib()
        try:
            return {"layer": layer, "neuron": neuron,
                    "results": [_entry(e) for e in lib.open(layer, neuron, model=lib_model(model))]}
        finally:
            lib.close()

    @app.get("/api/recent")
    def recent(k: int = 10, model: str | None = None):
        lib = open_lib()
        try:
            return {"results": [_entry(e) for e in lib.recent(k, model=lib_model(model))]}
        finally:
            lib.close()

    return app


def run_server(args: argparse.Namespace) -> int:
    import uvicorn

    if not args.model:  # resolve the id up front so catalogue endpoints work while loading
        if args.backend in ("mlx", "auto"):
            args.backend = "mlx"
            args.model = "mlx-community/Qwen3-8B-4bit"
        else:
            from .steer import DEFAULT_MODEL
            args.model = DEFAULT_MODEL
    app = create_app(args, load_model=not args.no_model)
    host = "localhost" if args.host in ("127.0.0.1", "localhost") else args.host
    url = f"http://{host}:{args.port}/"
    print(f"\n  Librarian of Alexandria — web chat\n  open {url}\n"
          f"  her voice: L{LIBRARIAN[0]} N{LIBRARIAN[1]} {LIBRARIAN[2]}  α={-abs(args.librarian_alpha):+g}  "
          f"model={args.model}\n"
          f"  About room teacher: {getattr(args, 'about_model', None) or about_mod.DEFAULT_ABOUT_MODEL} "
          f"(Bonsai 27B via {getattr(args, 'bonsai_url', None) or about_mod.DEFAULT_BONSAI_URL})\n"
          + ("  (loading the model in the background; the page shows when she is ready)\n" if not args.no_model
             else "  (--no-model: catalogue endpoints only)\n"), flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0
