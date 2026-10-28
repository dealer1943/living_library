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
import sys
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .library import DEFAULT_DB, LIBRARIAN, Entry, Library
from .librarian import LibrarianSession, _parse_dir, _parse_target, _split_prompt
from .prompts import DEFAULT_PROMPT, split_live

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
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health():
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
                r = srv.chat_sync(body, on_text=on_text, on_thought=on_thought)
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
