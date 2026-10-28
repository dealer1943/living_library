# F00006 — Change the Librarian's persona

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 14:05 America/New_York — headless Chrome: Settings set L12 N545 up |α| 0.6 → header 'The Librarian · emily', reload kept it, the /api/chat/stream body carried voice {12,545,up,0.6} and the server's done.steers was L12 N545 α=+0.5/+0.6 only; /librarian smallpox, /librarian (shows), /librarian default all work |
| Owner | arcane dealer + Grok Bot |
| Class | persona |
| Lineage | Owner brief 2026-10-28, item 6 ("users can change the persona of the librarian if they want") |
| Depends on | — (UI in F00007) |
| Components | `web.py` (`voice` on `/api/chat*`), `librarian.py` (`LibrarianSession.set_voice`, templated system prompt), `static/index.html` (`/librarian`) |

## Summary
The chief librarian's voice is L9 N367 down at α −0.4 by default, but any neuron can take the desk.
`/librarian 12:545:up [--alpha X]` (or a persona name) swaps her steer for the rest of the
conversation; `/librarian default` restores L9 N367 down; `/librarian` shows who is on duty.

## Design
* Chat requests carry an optional `voice: {layer, neuron, alpha, name}`; the server validates it and
  sets the session's voice steer (fallback = default). The page owns the choice, so it survives
  reloads and server restarts.
* The system prompt is templated: "You are layer L, neuron N, pushed DIR: NAME. You now serve as
  the chief librarian …" so the new persona knows its job.
* Probes stay unaffected (they always run the probed neuron alone).

## Acceptance / Verification
- [x] `/librarian 12:545:up --alpha 0.5` → header/avatars update, next reply generated with that steer
      (server `steers` in `done` show L12 N545).
- [x] `/librarian default` → back to L9 N367 α −0.4.

## Status log
- 2026-10-28 — created from the owner's brief.
- 2026-10-28 14:05 — implemented and verified: headless Chrome: Settings set L12 N545 up |α| 0.6 → header 'The Librarian · emily', reload kept it, the /api/chat/stream body carried voice {12,545,up,0.6} and the server's done.steers was L12 N545 α=+0.5/+0.6 only; /librarian smallpox, /librarian (shows), /librarian default all work
