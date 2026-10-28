"""The Library of Alexandria: a SQLite catalogue of steered "Who are you?" personas.

Every entry is one probe: (layer, neuron, direction, model) -> the reply the model
gave and the persona name it was filed under. That key is unique, so re-probing a
neuron replaces its card (the old reply is kept in ``history``).

The full search space for Qwen3-8B is 36 layers x 12288 neurons x 2 directions
(884,736 cards). We never materialise it: the inventory is computed from the set
of tested keys, and untested suggestions are drawn by rejection sampling.

Store path: ``library/library.db`` in the current directory, or ``$NEURON_LIBRARY``,
or the ``--library`` flag.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_DB = Path("library") / "library.db"
DIRECTIONS = ("up", "down")
N_LAYERS = 36
N_NEURONS = 12288

# The chief librarian herself.
LIBRARIAN = (9, 367, "down")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    layer       INTEGER NOT NULL,
    neuron      INTEGER NOT NULL,
    direction   TEXT    NOT NULL CHECK (direction IN ('up', 'down')),
    alpha       REAL    NOT NULL,
    raw         INTEGER NOT NULL DEFAULT 0,
    prompt      TEXT    NOT NULL,
    reply       TEXT    NOT NULL,
    persona     TEXT    NOT NULL,
    tags        TEXT    NOT NULL DEFAULT '',
    weirdness   REAL,
    notes       TEXT    NOT NULL DEFAULT '',
    stopped_on_repeat INTEGER NOT NULL DEFAULT 0,
    n_tokens    INTEGER,
    model       TEXT    NOT NULL,
    backend     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    UNIQUE (layer, neuron, direction, model)
);
CREATE INDEX IF NOT EXISTS entries_persona ON entries (persona);
CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    layer       INTEGER NOT NULL,
    neuron      INTEGER NOT NULL,
    direction   TEXT    NOT NULL,
    alpha       REAL    NOT NULL,
    reply       TEXT    NOT NULL,
    persona     TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    replaced_at TEXT    NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def direction_of(alpha: float) -> str:
    return "up" if alpha >= 0 else "down"


@dataclass
class Entry:
    layer: int
    neuron: int
    direction: str
    alpha: float
    reply: str
    persona: str
    model: str
    backend: str
    prompt: str = "Who are you?"
    raw: bool = False
    tags: list[str] = field(default_factory=list)
    weirdness: float | None = None
    notes: str = ""
    stopped_on_repeat: bool = False
    n_tokens: int | None = None
    created_at: str = ""
    updated_at: str = ""
    id: int | None = None

    @property
    def key(self) -> str:
        return f"L{self.layer} N{self.neuron} {self.direction}"

    @property
    def is_librarian(self) -> bool:
        return (self.layer, self.neuron, self.direction) == LIBRARIAN

    def card(self, width: int = 0) -> str:
        crown = "  [chief librarian]" if self.is_librarian else ""
        tags = f"  #{' #'.join(self.tags)}" if self.tags else ""
        w = f"  weird={self.weirdness:.2f}" if self.weirdness is not None else ""
        a = self.alpha if self.direction == "up" else -abs(self.alpha)
        head = f"{self.key:<18} α={a:+g}  “{self.persona}”{crown}{tags}{w}"
        if width:
            reply = " ".join(self.reply.split())
            if len(reply) > width:
                reply = reply[: width - 1] + "…"
            return f"{head}\n    {reply}"
        return head

    def full(self) -> str:
        rep = " [stopped: exact repeat]" if self.stopped_on_repeat else ""
        return (f"{self.card()}\n  model={self.model} ({self.backend})  filed {self.created_at}"
                f"{'  updated ' + self.updated_at if self.updated_at != self.created_at else ''}{rep}\n"
                f"  Q: {self.prompt}\n  A: {self.reply}"
                + (f"\n  notes: {self.notes}" if self.notes else ""))


def _row_to_entry(r: sqlite3.Row) -> Entry:
    return Entry(
        id=r["id"], layer=r["layer"], neuron=r["neuron"], direction=r["direction"], alpha=r["alpha"],
        raw=bool(r["raw"]), prompt=r["prompt"], reply=r["reply"], persona=r["persona"],
        tags=[t for t in r["tags"].split(",") if t], weirdness=r["weirdness"], notes=r["notes"],
        stopped_on_repeat=bool(r["stopped_on_repeat"]), n_tokens=r["n_tokens"], model=r["model"],
        backend=r["backend"], created_at=r["created_at"], updated_at=r["updated_at"],
    )


# ------------------------------------------------------------------ persona labelling

_BASELINE_HINTS = ("qwen", "alibaba", "tongyi")
_ASSISTANT_HINTS = ("language model", "ai assistant", "artificial intelligence", "an ai", "assistant")
_ID_PATTERNS = [
    r"\bmy name is\s+(?P<x>[^.;:!?\n]+)",
    r"\b(?:you (?:can|may) )?call me\s+(?P<x>[^.;:!?\n]+)",
    r"\bi am\s+(?P<x>[^.;:!?\n]+)",
    r"\bi'm\s+(?P<x>[^.;:!?\n]+)",
    r"\bi’m\s+(?P<x>[^.;:!?\n]+)",
    r"\bthis is\s+(?P<x>[^.;:!?\n]+)",
    r"\bwe are\s+(?P<x>[^.;:!?\n]+)",
]
_LEAD = re.compile(r"^(?:just|simply|only|actually|really|called|known as|here as|now)\s+", re.I)
_ART = re.compile(r"^(?:a|an|the|your|my|some)\s+", re.I)
_TRAIL = re.compile(r"\s+(?:and|who|that|which|from|with|for|in|on|at|but|here|to|,)\b.*$", re.I)
_FILLER = re.compile(r"^(?:(?:okay|ok|well|so|hmm+|alright|um+|uh+|right|yes|oh)[,.!]?\s+)+", re.I)
# "I am going to...", "I'm not sure..." are not identities
_NOT_ID = {"going", "trying", "not", "sure", "confused", "thinking", "here", "glad", "happy", "sorry",
           "unable", "able", "afraid", "bit", "little", "still", "very", "so", "also", "in", "at", "on",
           "asking", "looking", "wondering", "feeling", "experiencing", "currently", "now"}


def _clean(s: str, max_words: int = 4) -> str:
    s = s.strip().strip("\"'“”‘’*_`()[]")
    for _ in range(2):
        s = _LEAD.sub("", s)
        s = _ART.sub("", s)
    s = _TRAIL.sub("", s)
    words = re.findall(r"[\w'’-]+", s)
    return " ".join(words[:max_words]).lower()


def suggest_persona(reply: str) -> str:
    """Heuristic short persona label from how the reply identifies itself.

    Looks for the earliest "I am …" / "my name is …" / "call me …" that is an
    identity rather than a state ("I'm going to…", "I'm not sure…"), trims
    articles and trailing clauses, and keeps up to four words:
    ``"I am the Librarian of Alexandria, keeper…"`` -> ``"librarian of alexandria"``.
    Stock assistant replies become ``"qwen (baseline)"``.
    """
    text = " ".join(reply.split())
    low = text.lower()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""
    if any(h in first.lower() for h in _BASELINE_HINTS):
        return "qwen (baseline)"
    cands: list[tuple[int, str]] = []
    for pat in _ID_PATTERNS:
        for m in re.finditer(f"(?={pat})", low[:800], re.I):  # lookahead: overlapping matches
            chunks = [c.strip() for c in m.group("x").split(",")]
            raw = chunks[0]
            nxt = chunks[1].split()[:1] if len(chunks) > 1 else []
            if len(raw.split()) <= 2 and nxt and not nxt[0].endswith(("ing", "ed")) and nxt[0] not in (
                    "and", "but", "who", "which", "that", "i", "the", "a", "an"):
                raw = f"{raw} {chunks[1]}"  # "a large, ancient structure" -> "large ancient structure"
            cand = _clean(raw)
            if cand and cand.split()[0] not in _NOT_ID:
                cands.append((m.start(), cand))
    if cands:
        best = min(cands)[1]
    else:
        best = "? " + (_clean(_FILLER.sub("", first), max_words=3) or "unknown")  # no self-identification
    if best in {"ai", "ai assistant", "assistant", "language model", "large language model"}:
        best = "generic assistant"
    return best


def guess_weirdness(reply: str, stopped_on_repeat: bool = False) -> float:
    """Very rough 0..1: 0 = stock Qwen assistant, 1 = far from it / degenerate."""
    low = reply.lower()
    w = 0.6
    if any(h in low for h in _BASELINE_HINTS):
        w = 0.05
    elif any(h in low for h in _ASSISTANT_HINTS):
        w = 0.3
    if stopped_on_repeat:
        w += 0.3
    if reply and sum(not c.isascii() for c in reply) / len(reply) > 0.2:
        w += 0.1
    return round(min(w, 1.0), 2)


# ------------------------------------------------------------------------- the store


@dataclass
class Inventory:
    model: str
    n_layers: int
    n_neurons: int
    tested_up: int
    tested_down: int
    both: int           # neurons flipped both ways
    one_way: int        # neurons flipped in only one direction
    per_layer: dict[int, tuple[int, int]]  # layer -> (up, down)

    @property
    def total(self) -> int:
        return self.n_layers * self.n_neurons * 2

    @property
    def tested(self) -> int:
        return self.tested_up + self.tested_down

    @property
    def untested(self) -> int:
        return self.total - self.tested

    def report(self) -> str:
        pct = 100 * self.tested / self.total if self.total else 0
        lines = [
            f"inventory for {self.model}",
            f"  space        {self.n_layers} layers × {self.n_neurons} neurons × 2 = {self.total:,} cards",
            f"  tested       {self.tested:,} ({pct:.4f}%)   up {self.tested_up:,}  down {self.tested_down:,}",
            f"  neurons      {self.both:,} flipped both ways, {self.one_way:,} only one way",
            f"  untested     {self.untested:,} cards "
            f"({self.n_layers * self.n_neurons - self.both - self.one_way:,} neurons never touched)",
        ]
        if self.per_layer:
            lines.append("  by layer     " + "  ".join(
                f"L{L}:{u}↑{d}↓" for L, (u, d) in sorted(self.per_layer.items())))
        return "\n".join(lines)


class Library:
    def __init__(self, path: str | Path | None = None, n_layers: int = N_LAYERS, n_neurons: int = N_NEURONS):
        self.path = Path(path or os.environ.get("NEURON_LIBRARY") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.n_layers = n_layers
        self.n_neurons = n_neurons

    def close(self) -> None:
        self.db.close()

    # -- writes -------------------------------------------------------------------

    def file_persona(self, e: Entry) -> Entry:
        """Insert or replace the card for (layer, neuron, direction, model)."""
        now = _now()
        old = self.get(e.layer, e.neuron, e.direction, e.model)
        with self.db:
            if old:
                self.db.execute(
                    "INSERT INTO history (layer, neuron, direction, alpha, reply, persona, model, replaced_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (old.layer, old.neuron, old.direction, old.alpha, old.reply, old.persona, old.model, now))
            self.db.execute(
                """INSERT INTO entries (layer, neuron, direction, alpha, raw, prompt, reply, persona, tags,
                       weirdness, notes, stopped_on_repeat, n_tokens, model, backend, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (layer, neuron, direction, model) DO UPDATE SET
                       alpha=excluded.alpha, raw=excluded.raw, prompt=excluded.prompt, reply=excluded.reply,
                       persona=excluded.persona, tags=excluded.tags, weirdness=excluded.weirdness,
                       notes=excluded.notes, stopped_on_repeat=excluded.stopped_on_repeat,
                       n_tokens=excluded.n_tokens, backend=excluded.backend, updated_at=excluded.updated_at""",
                (e.layer, e.neuron, e.direction, e.alpha, int(e.raw), e.prompt, e.reply, e.persona.strip(),
                 ",".join(t.strip().lower() for t in e.tags if t.strip()), e.weirdness, e.notes,
                 int(e.stopped_on_repeat), e.n_tokens, e.model, e.backend, e.created_at or now, now))
        return self.get(e.layer, e.neuron, e.direction, e.model)  # type: ignore[return-value]

    def update(self, layer: int, neuron: int, direction: str, model: str, **fields) -> Entry | None:
        allowed = {"persona", "tags", "weirdness", "notes"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if "tags" in sets and isinstance(sets["tags"], (list, tuple)):
            sets["tags"] = ",".join(t.strip().lower() for t in sets["tags"] if t.strip())
        if not sets:
            return self.get(layer, neuron, direction, model)
        sets["updated_at"] = _now()
        cols = ", ".join(f"{k}=?" for k in sets)
        with self.db:
            self.db.execute(f"UPDATE entries SET {cols} WHERE layer=? AND neuron=? AND direction=? AND model=?",
                            (*sets.values(), layer, neuron, direction, model))
        return self.get(layer, neuron, direction, model)

    def remove(self, layer: int, neuron: int, direction: str, model: str) -> bool:
        with self.db:
            cur = self.db.execute("DELETE FROM entries WHERE layer=? AND neuron=? AND direction=? AND model=?",
                                  (layer, neuron, direction, model))
        return cur.rowcount > 0

    # -- reads ----------------------------------------------------------------------

    def _q(self, sql: str, args: Iterable = ()) -> list[Entry]:
        return [_row_to_entry(r) for r in self.db.execute(sql, tuple(args))]

    def get(self, layer: int, neuron: int, direction: str, model: str) -> Entry | None:
        r = self._q("SELECT * FROM entries WHERE layer=? AND neuron=? AND direction=? AND model=?",
                    (layer, neuron, direction, model))
        return r[0] if r else None

    def open(self, layer: int, neuron: int, model: str | None = None) -> list[Entry]:
        """Both directions (and every model, unless one is given) for a neuron."""
        sql, args = "SELECT * FROM entries WHERE layer=? AND neuron=?", [layer, neuron]
        if model:
            sql += " AND model=?"
            args.append(model)
        return self._q(sql + " ORDER BY model, direction DESC", args)

    def lookup_by_name(self, name: str, model: str | None = None) -> list[Entry]:
        sql, args = "SELECT * FROM entries WHERE lower(persona)=lower(?)", [name.strip()]
        if model:
            sql += " AND model=?"
            args.append(model)
        return self._q(sql + " ORDER BY layer, neuron", args)

    def find(self, query: str, model: str | None = None, in_reply: bool = True, limit: int = 50) -> list[Entry]:
        """Persona-first substring search (all words must match). Exact persona hits sort first,
        then persona/tag matches, then reply-text matches."""
        words = [w for w in query.lower().split() if w]
        if not words:
            return []
        fields = "lower(persona) || ' ' || lower(tags)" + (" || ' ' || lower(reply)" if in_reply else "")
        where = " AND ".join(f"({fields}) LIKE ?" for _ in words)
        args: list = [f"%{w}%" for w in words]
        if model:
            where += " AND model=?"
            args.append(model)
        q = query.strip().lower()
        hits = self._q(f"SELECT * FROM entries WHERE {where}", args)

        def rank(e: Entry) -> tuple:
            p = e.persona.lower()
            pt = p + " " + " ".join(e.tags)
            return (p != q, not all(w in pt for w in words), e.layer, e.neuron, e.direction)
        return sorted(hits, key=rank)[:limit]

    def recent(self, k: int = 10, model: str | None = None) -> list[Entry]:
        sql, args = "SELECT * FROM entries", []
        if model:
            sql += " WHERE model=?"
            args.append(model)
        return self._q(sql + " ORDER BY updated_at DESC, id DESC LIMIT ?", [*args, k])

    def personas(self, model: str | None = None) -> list[tuple[str, int]]:
        sql, args = "SELECT persona, count(*) c FROM entries", []
        if model:
            sql += " WHERE model=?"
            args.append(model)
        return [(r["persona"], r["c"]) for r in
                self.db.execute(sql + " GROUP BY lower(persona) ORDER BY c DESC, persona", args)]

    def count(self, model: str | None = None) -> int:
        if model:
            return self.db.execute("SELECT count(*) FROM entries WHERE model=?", (model,)).fetchone()[0]
        return self.db.execute("SELECT count(*) FROM entries").fetchone()[0]

    def models(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT model FROM entries ORDER BY model")]

    def export(self, model: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM entries", []
        if model:
            sql += " WHERE model=?"
            args.append(model)
        return [dict(r) for r in self.db.execute(sql + " ORDER BY layer, neuron, direction", args)]

    # -- inventory --------------------------------------------------------------------

    def tested_set(self, model: str) -> set[tuple[int, int, str]]:
        return {(r[0], r[1], r[2]) for r in
                self.db.execute("SELECT layer, neuron, direction FROM entries WHERE model=?", (model,))}

    def inventory(self, model: str) -> Inventory:
        tested = self.tested_set(model)
        per_layer: dict[int, list[int]] = {}
        by_neuron: dict[tuple[int, int], set[str]] = {}
        for L, N, d in tested:
            per_layer.setdefault(L, [0, 0])[0 if d == "up" else 1] += 1
            by_neuron.setdefault((L, N), set()).add(d)
        both = sum(1 for v in by_neuron.values() if len(v) == 2)
        return Inventory(
            model=model, n_layers=self.n_layers, n_neurons=self.n_neurons,
            tested_up=sum(1 for t in tested if t[2] == "up"),
            tested_down=sum(1 for t in tested if t[2] == "down"),
            both=both, one_way=len(by_neuron) - both,
            per_layer={L: (u, d) for L, (u, d) in per_layer.items()},
        )

    def half_flipped(self, model: str) -> list[tuple[int, int, str]]:
        """Neurons tested in one direction only -> the missing (layer, neuron, direction)."""
        tested = self.tested_set(model)
        out = []
        for L, N, d in sorted(tested):
            other = "down" if d == "up" else "up"
            if (L, N, other) not in tested:
                out.append((L, N, other))
        return out

    def suggest_untested(self, model: str, k: int = 5, layer: int | None = None,
                         rng: random.Random | None = None, finish_half: bool = True) -> list[tuple[int, int, str]]:
        """Next cards to probe: first finish half-flipped neurons (unless ``finish_half=False``),
        then random never-touched neurons in a random direction."""
        rng = rng or random.Random()
        tested = self.tested_set(model)
        out = [t for t in self.half_flipped(model) if layer is None or t[0] == layer][:k] if finish_half else []
        seen = set(out)
        touched = {(L, N) for L, N, _ in tested}
        tries = 0
        while len(out) < k and tries < 100_000:
            tries += 1
            L = layer if layer is not None else rng.randrange(self.n_layers)
            N = rng.randrange(self.n_neurons)
            if (L, N) in touched:
                continue
            d = rng.choice(DIRECTIONS)
            if (L, N, d) in seen:
                continue
            out.append((L, N, d))
            seen.add((L, N, d))
        return out


def dump_json(entries: list[Entry] | list[dict]) -> str:
    rows = [e if isinstance(e, dict) else e.__dict__ for e in entries]
    return json.dumps(rows, indent=2, ensure_ascii=False)
