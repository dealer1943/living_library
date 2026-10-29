# F00010 — Rename tabs (`/name`, ✎, double-click)

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 18:04 America/New_York — headless Chrome over CDP (ll_uitest.mjs, 18/18 checks, 0 page errors): `/name Desk test` renamed the desk (header, sidebar, document.title) and survived a reload; ✎ in the sidebar → inline input → Enter set a persona tab to "Keeper", persisted across reload |
| Owner | arcane dealer + Grok Bot |
| Class | ux |
| Lineage | Owner, 2026-10-28: "a couple of times I wanted to rename the chat… a /name makes sense, or a click on the neuron layer in the tab on the left, or top left too" |
| Depends on | F00004 |
| Components | `static/index.html` (`baseName`/`dispName`, `renameTab`, `editName`, `/name` in COMMANDS) |

## Summary
Any tab — the Librarian's desk, a persona, a mix or a group — can carry a display **label**.
`/name LABEL` sets it for the active tab; clicking the title top-left, double-clicking a tab in the
left sidebar, or its ✎ button edits it inline. The label is display-only: the persona name sent to
the model is unchanged.

## Design
- Stored as `t.label` in localStorage (`librarian-chat-v2`), so it survives reload; max 60 chars.
- `dispName(t)` = label or base name; used in the sidebar, header, `document.title`, `/tabs`, the
  check-in note, the chat export (`label` field; markdown title "label (name)") and the share card.
- Sidebar rows show the label with the base name (e.g. `L11 N111 up α +0.7`) underneath.
- `/name` alone shows the current name; `/name reset` (or `clear`, `default`, `-`) or an empty
  inline edit restores the default. `/rename` is an alias. Tab lookup (`/alpha NAME`, `/checkin NAME`) also matches labels.

## UX spec
Inline edit: Enter or blur saves, Esc cancels. Re-renders while the input is open are held off so it never disappears mid-typing.

## Acceptance / Verification
- [x] `/name X` renames the active tab everywhere; persists across reload.
- [x] ✎ / double-click in the sidebar and click on the header title rename inline.
- [x] `/name reset` restores the default; the model still sees the original persona name.
- [x] On a persona tab the label also drives the avatar letter (sidebar, empty state, share card), the bubble "who" line and avatar letter (stored and live), the empty-state heading/lead and the input placeholder (`showWho(t, who)`); existing bubbles re-render on rename. Model-facing names (`t.name`, member names, transcript speakers) are unchanged.

## Status log
- 2026-10-28 — created from the owner's bug report.
- 2026-10-28 18:04 — implemented and verified: headless Chrome over CDP (ll_uitest.mjs, 18/18 checks, 0 page errors).
- 2026-10-28 22:10 — fix from owner's bug report ("the C conversation should be E espresso"): label now drives avatar initial, bubble who, share card, empty state and placeholder; model name unchanged. JS syntax-checked with `node --check`; not re-run in a browser.
