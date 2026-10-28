# F00007 — Settings (top right): set the Librarian's neuron or restore default

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 14:05 America/New_York — headless Chrome: ⚙ (top right) opens the drawer; Esc, ✕, backdrop and /settings open/close it; Make librarian by L/N/dir/α and by filed persona name; Restore default → L9 N367 down α −0.4 |
| Owner | arcane dealer + Grok Bot |
| Class | settings |
| Lineage | Owner brief 2026-10-28, item 7 ("settings in the top right lets users change the librarian to a new neuron, or return to default") |
| Depends on | F00006 |
| Components | `static/index.html` (settings drawer) |

## Summary
A ⚙ button in the top-right header opens a Settings drawer. Its first section, **Librarian**,
shows the neuron on duty and lets you set a new one (layer, neuron, up/down, |α|, or pick a
filed persona / checked-out tab) or **Restore default (L9 N367 down, α −0.4)**. The drawer is
also the home for Export (F00008) and Skins (F00009).

## UX spec
* ⚙ top right → drawer slides in from the right; Esc or clicking outside closes it; `/settings` opens it.
* Librarian section: current voice line, inputs (L, N, direction toggle, |α|), "Make librarian",
  "Restore default". Changes post a catalogue note in the Librarian tab.

## Acceptance / Verification
- [x] ⚙ opens/closes the drawer (button, Esc, backdrop, `/settings`).
- [x] Setting L/N/dir/α changes the Librarian voice (same effect as `/librarian`), persists across reload.
- [x] Restore default returns to L9 N367 down α −0.4.

## Status log
- 2026-10-28 — created from the owner's brief.
- 2026-10-28 14:05 — implemented and verified: headless Chrome: ⚙ (top right) opens the drawer; Esc, ✕, backdrop and /settings open/close it; Make librarian by L/N/dir/α and by filed persona name; Restore default → L9 N367 down α −0.4
