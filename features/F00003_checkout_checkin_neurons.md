# F00003 — Check out / check in neurons (with five-keyword check-in)

| Field | Value |
|-------|-------|
| State | Planned |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | pending |
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

## Acceptance / Verification
- [ ] Checkout by spec and by persona name opens a tab with the right steer.
- [ ] Persona replies stream and are generated with that steer only.
- [ ] Check-in with 5 typed keywords stores `source=user`.
- [ ] Check-in skipped → 5 keywords from the Librarian, `source=librarian`, stored in `checkouts`
      and merged into the card's tags.

## Open questions / follow-ups
- Due dates / "overdue" neurons; check-out history view (`/ledger`).

## Status log
- 2026-10-28 — created from the owner's brief.
