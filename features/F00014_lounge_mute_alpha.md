# F00014 — The Lounge: everyone checked in, at one table (mute, per-voice α, α kept on check-in)

| Field | Value |
|-------|-------|
| State | Verified |
| Stage | pre-MVP |
| Created | 2026-10-29 |
| Verified | 2026-10-29 08:38 |
| Owner | arcane dealer + Grok Bot |
| Class | ux / persona |
| Lineage | Owner brief 2026-10-29: a special room where everyone who has been checked in chats together; on/off, reset, archive; mute; per-voice α "when someone repeats themselves"; keep the α a tab had at check-in |
| Depends on | F00003, F00004, F00005, F00013 |
| Components | `static/index.html` (`getLounge`, `shelfVoices`, `syncLounge`, `loungeCmd`, `renderLoungeBar`, `personaBody`, `sendPersona`, `doCheckin`, `renderTabs`); reuses `POST /api/persona/stream` (`mode: group`) — no server change |

## Summary
A **Lounge** tab (sidebar, under the Desk) where every voice on the shelf (`tabs.shelf`, everyone checked in)
talks together, group-chat style: you speak, then each unmuted voice answers in turn, hearing the others.
It can be turned **on/off**, **reset** (clear messages), and **archived** (hidden, history kept, `/lounge`
reopens it). Any voice can be **muted** (skips its turns) and given its **own α**. Check-in now snapshots
each member's *current* α (after `/alpha` edits), and that is the α the voice has on the shelf and in the Lounge.

## Motivation
Check-in closes a persona's private room; the Lounge gives the shelf a second life — the personas you've met,
meeting each other. Steered voices loop at high α, so lowering one voice's α (or muting it) is the fix in a room.

## Design
- **Tab**: one special tab `{ id: "lounge", kind: "lounge", name: "The Lounge", members, messages, on, created_at }`,
  kept at `tabs.tabs[1]` (so Ctrl+2 is the Lounge), persisted in `librarian-chat-v2` like any tab.
  Archived: moved to `tabs.loungeArchive` (with `archived_at`); `/lounge` puts it back.
  `isLounge(t)`; `isOut(t)` = a checked-out persona tab (the Lounge is persona-like but never checked out/in,
  so `/checkin all`, `/tabs`, desk `/alpha`, export "active neurons" and `findTab` use `isOut`).
- **Membership** (`syncLounge`): unique `layer|neuron|direction` across the shelf; the newest check-in of a voice
  wins. Mix/group check-ins contribute each member as its own voice. New voices are appended (oldest check-in
  first, members in tab order). Lounge-side α edits and mutes stick until that voice is **checked in again**
  (a newer `checked_in_at`), which resets its lounge α/name to the new check-in. Voices no longer on the
  shelf (cap 50) leave. Two voices with one name get `(L N)` appended (the name is who the model is told it is).
  Synced on: every check-in (announced in the Lounge when it's open and on; quiet when off or archived),
  opening/switching to the Lounge tab, `/lounge`, `/lounge sync`, ⟳ Sync.
- **Turns**: `sendPersona` treats the Lounge like a group; `personaBody` sends `mode: "group"` with the
  *unmuted* members (speaker always included), each at its own α; mute and off are re-checked before each
  speaker, so muting mid-round counts. Token-limit continuation (F00013) works the same.
- **Refusals** (text handed back, nothing sent): empty shelf ("Nobody on the shelf yet — check someone in first"),
  lounge off, everyone muted.
- **α on check-in** (`doCheckin`): members are snapshotted as `{...m, alpha: |m.alpha|}` *before* the request;
  that snapshot is what `POST /api/checkin` logs (the server already logs the α it is sent — it does not read the
  card) and what the shelf entry stores. `/checkout NAME` of a shelf voice **restores that shelf α**
  automatically (unless the checkout spec passes an explicit α, e.g. `/checkout emily --alpha 1`).

## UX spec
- Sidebar: **Lounge** section under Desk — the tab row (⏸/▶ power button on hover), or a dashed
  "☕ Open the lounge · N on the shelf" / "↺ Reopen the lounge · N msgs archived" button.
- In the Lounge, a bar above the composer: ● on / ○ off, one chip per voice (its color, name, **α** number box —
  Enter or blur applies, **mute/unmute** button), then ⏸ Turn off / ▶ Turn on · ⟳ Sync · Reset (confirms) · Archive.
- Header subtitle: `lounge on · 3 voices (1 muted)`; the composer placeholder lists who will answer.
- Commands: `/lounge` (= on/open/reopen) · `/lounge off` · `/lounge reset` · `/lounge archive` · `/lounge sync` ·
  `/lounge status` · `/mute NAME` · `/unmute NAME|all` (work from any tab) · `/alpha NAME X` in the Lounge
  (name, `/name` label, or L:N). The Clear button also clears the Lounge. `/checkin` in the Lounge explains it can't.

## Acceptance / Verification
- [x] `/alpha 0.35` in a persona tab, check in → Librarian note and shelf show α 0.35; Lounge has that voice at 0.35.
- [x] Group/mix check-in with one member re-tuned → each member joins the Lounge separately at its own α.
- [x] Lounge round: each unmuted voice answers in order, hearing the others; muted voices skip.
- [x] `/alpha NAME X` and the chip's α box change only that voice; takes effect on its next turn.
- [x] Off → sending is refused and nobody speaks; On → resumes.
- [x] Reset clears messages, keeps voices/mutes/α. Archive hides the tab, history kept; `/lounge` reopens it.
- [x] Empty shelf → "Nobody on the shelf yet — check someone in first".
- [x] Single / mix / group checkout and chat unchanged.
- [x] Re-checkout of a shelf voice (`/checkout NAME`) restores its shelf α (explicit `--alpha` still overrides).

## Open questions / follow-ups
- A big shelf means long rounds — maybe a "max speakers per round" or random order later.

## Status log
- 2026-10-29 08:30 — created and implemented (index.html only). Pre-check: headless Chrome over CDP with
  `/api/checkin` and `/api/persona/stream` stubbed in-page (no DB writes, no model): 20/20 lounge checks + single/group
  regression, 0 page errors. Awaiting owner verification on the real model.
- 2026-10-29 08:35 — re-checkout now restores last check-in α (owner: emily came back at 1.0 after check-in at 0.7).
- 2026-10-29 08:38 — Verified by owner on the real model.
