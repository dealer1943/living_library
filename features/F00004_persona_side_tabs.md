# F00004 — A side tab for each persona

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 14:21 America/New_York — headless Chrome (f345.js): v1 chat migrated into the Librarian tab; switching to the Librarian (Ctrl+1) mid-stream left emily busy and its reply raised the unread dot; Ctrl+2 back showed the finished reply; tabs and the shelf survived reload; 420 px ☰ drawer checked by screenshot |
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

## As built (2026-10-28)
* Left sidebar (`nav#tabs`): **Desk** (the Librarian, showing her current voice) and **Checked out**
  (one tab per checkout: avatar in the persona's color — split for a mix, stacked for a group — name,
  steer summary, unread dot, ↩ check-in button), *＋ Check out a persona* (pre-types `/checkout `), and
  a footer with the shelf count and shortcuts. Ctrl+1…9 jump; Alt+↑/↓ cycle. Under 760 px it becomes a
  drawer behind a ☰ button (tap outside to close).
* State `librarian-chat-v2` = `{tabs, active, shelf}`; v1 messages migrate into the Librarian tab (the
  v1 key is left untouched). Messages carry `at` timestamps.
* Streams belong to the tab that started them (`lives` map): switching away and back re-attaches the
  in-flight bubble; a finished reply in a background tab sets its unread dot (catalogue notes don't).
  Busy is per tab — the composer is only disabled in the tab that is waiting.
* Header follows the active tab: title, steers, composer placeholder ("Message emily…"), a
  **↩ Check in** button, and *Clear* (instead of *New chat*) for persona tabs.

## Acceptance / Verification
- [x] Librarian tab + one tab per checkout; switching keeps each history separate.
- [x] Reload keeps tabs and messages.
- [x] Reply streaming into a background tab marks it unread.

## Status log
- 2026-10-28 — created from the owner's brief.
- 2026-10-28 14:21 — implemented and verified: headless Chrome (f345.js): v1 chat migrated into the Librarian tab; switching to the Librarian (Ctrl+1) mid-stream left emily busy and its reply raised the unread dot; Ctrl+2 back showed the finished reply; tabs and the shelf survived reload; 420 px ☰ drawer checked by screenshot
