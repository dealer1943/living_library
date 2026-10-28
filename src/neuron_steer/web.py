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
        if not msg:
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
        res = s.chat(msg, on_text=on_text, on_thought=on_thought)
        return {"session_id": sid, "reply": res.text, "thoughts": res.thoughts, "n_tokens": res.n_new_tokens,
                "stopped_on_repeat": res.stopped_on_repeat, "turns": len(s.history) // 2,
                "steers": [_steer(x) for x in s.steers],
                "applied": [str(a) for a in res.applied]}

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

    def persona_sync(self, body: dict, on_text=None) -> dict:
        """One reply in a persona tab. mode single|mix: every member pushed at once, one voice;
        mode group: only ``members[speaker]`` speaks, seeing the whole shared transcript."""
        if self.base is None:
            raise RuntimeError(self.error or "model not loaded")
        s = self.base
        members = list(body.get("members") or [])
        mode = str(body.get("mode") or ("mix" if len(members) > 1 else "single"))
        transcript = [t for t in (body.get("transcript") or []) if isinstance(t, dict)]
        if mode == "group":
            i = int(body.get("speaker", 0))
            me = members[i]
            steers = self._steers([me])
            names = [str(m.get("name") or f"L{m['layer']} N{m['neuron']}") for m in members]
            msgs = persona_messages(transcript, names[i], group=names)
            max_new = int(body.get("max_new_tokens") or 200)
        else:
            steers = self._steers(members)
            name = str(body.get("name") or "persona")
            msgs = persona_messages(transcript, name)
            max_new = int(body.get("max_new_tokens") or s.max_new_tokens)
        if not msgs or msgs[-1]["role"] != "user":
            raise ValueError("the transcript must end with a message to the persona")
        self.base.lab.validate(steers)
        from .librarian import _separate
        res = _separate(s.generate(msgs, steers, max_new_tokens=max_new, on_text=on_text))
        text = strip_speaker(res.text, names[i]) if mode == "group" else res.text
        if mode == "group" and is_echo(text, transcript):   # parroted the room: one more try
            res = _separate(s.generate(msgs, steers, max_new_tokens=max_new, on_text=on_text))
            text = strip_speaker(res.text, names[i])
        spill, reply = split_live(text)  # untagged reasoning ("Okay, let me figure out…") -> thoughts
        thoughts = "\n\n".join(x for x in (res.thoughts, spill) if x.strip())
        text = trim_repeats(reply if reply.strip() else text)
        return {"reply": text, "thoughts": thoughts, "n_tokens": res.n_new_tokens, "mode": mode,
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
                "catalogue": str(_db_path(args))}

    @app.post("/api/chat")
    async def chat(body: dict = Body(...)):
        return await guarded(srv.chat_sync, body)

    @app.post("/api/chat/stream")
    async def chat_stream(body: dict = Body(...)):
        return sse(lambda on_text, on_thought: srv.chat_sync(body, on_text=on_text, on_thought=on_thought))

    @app.post("/api/persona/stream")
    async def persona_stream(body: dict = Body(...)):
        """F00003–F00005: a checked-out persona's reply (single, --mix blend, or one group member)."""
        return sse(lambda on_text, on_thought: srv.persona_sync(body, on_text=on_text))

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

    def sse(work):
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
            spill, reply = split_live("".join(raw))
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

        srv.pool.submit(job)

        async def events():
            yield f"data: {json.dumps({'type': 'queued', 'ready': srv.ready.is_set()})}\n\n"
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
          + ("  (loading the model in the background; the page shows when she is ready)\n" if not args.no_model
             else "  (--no-model: catalogue endpoints only)\n"), flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0
