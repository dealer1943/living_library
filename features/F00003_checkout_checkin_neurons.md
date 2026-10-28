# F00003 — Check out / check in neurons (with five-keyword check-in)

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 14:21 America/New_York — headless Chrome (f345.js): /checkout emily opened its tab with L12 N545 up α +1.0 and /api/persona/stream sent only that steer; Check in with 'Poetic Wistful garden sea quiet extra' showed 6/5 chips and stored 'poetic wistful garden sea quiet' (source=user, card tags merged); Skip on the group stored 5 librarian keywords (source=librarian); /checkin all and reload persistence OK; 0 page errors |
| Owner | arcane dealer + Grok Bot |
| Class | persona |
| Lineage | Owner brief 2026-10-28, item 3 (check in / check out; optional "five space separated keywords"; Librarian auto-populates from the chat if skipped) |
| Depends on | F00004 (a checked-out persona lives in its own tab) |
| Components | `web.py` (`/api/checkout`, `/api/checkin`, `/api/persona/stream`), `library.py` (`checkouts` table), `librarian.py` (keyword auto-fill), `static/index.html` |

## Summary
Like a library book: `/checkout 12:545:up` borrows that neuron's persona so you can talk to it
directly; `/checkin` returns it. Check-in asks, optionally, *"Could you provide five
space-separated keywords to describe this persona?"* — if you skip, the Librarian reads the chat
and fills the five keywords in herself. Each check-in is logged in the catalogue.

## Design
**Commands**
* `/checkout L:N[:up|down][:α] [--alpha X]` — also `L12 N545 up`, or a filed persona name
  (`/checkout smallpox`). Direction defaults to the filed card's direction (or `up`).
  |α| defaults to the filed card's α, else 1.0.
* `/checkin` — in a persona tab, checks that tab in. In the Librarian tab, `/checkin L:N[:dir]`
  or `/checkin all`.

**API**
* `POST /api/checkout {spec}` → `{mode, name, members:[{layer, neuron, direction, alpha, persona, filed}]}`
  (parse + catalogue lookup, no model needed).
* `POST /api/persona/stream {members, mode, transcript, speaker}` → SSE `reply`/`spill`/`done`,
  generated with only that persona's steer(s) active (never the Librarian's voice), thinking off.
* `POST /api/checkin {members, mode, name, transcript, keywords?, checked_out_at}` →
  `{keywords:[5], source:"user"|"librarian"}`. Blank keywords → the Librarian (her voice, thinking
  off) is shown the transcript and asked for exactly five lowercase keywords; output is
  normalised (lowercase, de-duplicated, stop-words dropped) and topped up from the transcript's
  most frequent content words if she gives fewer than five.

**Catalogue**: new table `checkouts` (layer, neuron, direction, alpha, mode, group_name,
keywords, keyword_source, turns, checked_out_at, checked_in_at, model). If the neuron has a filed
card, the keywords are also merged into the card's tags so `/find` finds them.

## UX spec
1. `/checkout 12:545:up` → a new side tab opens and becomes active, named after the card.
2. Chat normally; the header shows the persona's steer.
3. `/checkin` (or the tab's ✓ button) → a dialog: the question, a keyword field with live chips
   (n/5), **Check in** and **Skip — let the Librarian fill it in**.
4. Tab closes; the Librarian tab gets a catalogue note: `checked in L12 N545 up · keywords: … (by the Librarian)`.

## As built (2026-10-28)
* **Server** — `personas.py` (transcript → chat messages, keyword prompt + normalisation, echo / repeat
  trimming); `web.py`: `POST /api/persona/stream` (SSE, same events as the Librarian chat; only the
  persona's steers; thinking off), `POST /api/checkin`, `GET /api/checkins`; `library.py`: `checkouts`
  table + `log_checkin()` (one row per member; keywords merged into a filed card's tags) + `checkins()`.
* **Keywords** — typed ones are lower-cased and de-duplicated, max 5 (`source=user`). Blank → the
  Librarian (her default voice, ~24 tokens, thinking off) is asked for exactly five; her answer is
  cleaned (stop-words and the personas' own names dropped) and topped up from the chat's most frequent
  content words if she gives fewer (`source=librarian`). With `--no-model` it is frequency-only.
* **Commands** — `/checkout NAME | L:N[:dir][:α] [+ …] [--mix] [--alpha X]` (alias `/co`), `/checkin`
  (this tab), `/checkin NAME|L:N`, `/checkin all` (Librarian picks for everyone), `/alpha X | NAME X`
  (retune the tab's push), `/tabs` (who is out + the last check-ins). A second `/checkout` of the
  same neuron(s) and mode switches to the open tab instead of duplicating it.
* **Default chat α** — the card's filed α capped at **1.0** (`CHAT_ALPHA_CAP`), else 1.0. A sweep of
  0.5 / 0.75 / 1.0 / 1.25 on “Hi! Who are you?”: ≤0.5 both cards answer as plain Qwen; smallpox holds
  character at 0.75–1.0 and collapses into loops at 1.25; emily drifts into letter puzzles at ≥1.0.
* **Dialog** — avatar, member labels, turns and time out; the question verbatim; live keyword chips
  with an n/5 counter (extras struck through); *Keep chatting* · *Skip — let the Librarian fill it in*
  · *Check in* (Enter). While she reads the chat the dialog shows “The Librarian is reading the chat…”
  and can't be dismissed. The result is posted to the Librarian's tab; the tab's chat moves to the
  shelf (kept for export).

## Acceptance / Verification
- [x] Checkout by spec and by persona name opens a tab with the right steer.
- [x] Persona replies stream and are generated with that steer only.
- [x] Check-in with 5 typed keywords stores `source=user`.
- [x] Check-in skipped → 5 keywords from the Librarian, `source=librarian`, stored in `checkouts`
      and merged into the card's tags.

## Open questions / follow-ups
- Due dates / "overdue" neurons; check-out history view (`/ledger`).
- Per-persona memory across checkouts (re-checkout resumes the last chat?) — not yet; the shelf keeps
  the chats, the catalogue keeps the keywords.
- Steered voices are unstable at α ≥ 1 (loops, puzzle-solving, reasoning aloud). Untagged reasoning is
  folded into *Thoughts* and repeated sentences are trimmed; `/alpha` is the user's dial.

## Status log
- 2026-10-28 — created from the owner's brief.
- 2026-10-28 14:21 — implemented and verified: headless Chrome (f345.js): /checkout emily opened its tab with L12 N545 up α +1.0 and /api/persona/stream sent only that steer; Check in with 'Poetic Wistful garden sea quiet extra' showed 6/5 chips and stored 'poetic wistful garden sea quiet' (source=user, card tags merged); Skip on the group stored 5 librarian keywords (source=librarian); /checkin all and reload persistence OK; 0 page errors
