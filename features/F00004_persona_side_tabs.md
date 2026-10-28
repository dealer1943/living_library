# F00004 — A side tab for each persona

| Field | Value |
|-------|-------|
| State | Planned |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | pending |
| Owner | arcane dealer + Grok Bot |
| Class | ux / persona |
| Lineage | Owner brief 2026-10-28, item 4 ("each persona gets a side tab … a dedicated space to chat with the persona") |
| Depends on | F00003 |
| Components | `static/index.html` (sidebar, per-tab state in localStorage) |

## Summary
A left sidebar lists the Librarian (always first, can't be closed) and one tab per checked-out
persona or group. Each tab is its own conversation with its own history, header and steer; switching
tabs swaps the whole chat. Tabs survive reloads and server restarts (localStorage).

## Design
* State `librarian-chat-v2`: `{tabs:[{id, kind:"librarian"|"persona"|"mix"|"group", name, members,
  messages, session_id, checked_out_at}], active}`; v1 history migrates into the Librarian tab.
* Each tab shows: avatar initials, name, steer summary, and an unread dot when a reply lands while
  you are elsewhere.
* "+ Check out" in the sidebar focuses the box with `/checkout ` pre-typed (slash menu opens).
* Keyboard: Ctrl/⌘+1…9 jumps to tab n. On narrow screens the sidebar collapses behind a ☰ button.
* Slash commands work in every tab; plain text goes to the active tab's persona(s).

## Acceptance / Verification
- [ ] Librarian tab + one tab per checkout; switching keeps each history separate.
- [ ] Reload keeps tabs and messages.
- [ ] Reply streaming into a background tab marks it unread.

## Status log
- 2026-10-28 — created from the owner's brief.
