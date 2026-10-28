# F00011 — Copy button under each chat bubble

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 18:04 America/New_York — headless Chrome over CDP (ll_uitest.mjs, 18/18 checks, 0 page errors): every bubble (14/14) had a copy button; click wrote the message to the clipboard and flashed "Copied" |
| Owner | arcane dealer + Grok Bot |
| Class | ux |
| Lineage | Owner steer 2026-10-28: "copy button under each chat bubble (user + librarian/persona)" |
| Depends on | — |
| Components | `static/index.html` (`.acts` row in `msgBubble`, `copyText`, delegated `log` click handler) |

## Summary
A small action row under every bubble — yours, the Librarian's, a persona's, commands and system
notes — with **Copy** (the message's plain text, without the thoughts) and **Share** (F00012).

## Design
`navigator.clipboard.writeText`, falling back to a hidden textarea + `execCommand("copy")` on
plain-http hosts. The row fades in on hover (always visible on touch); the button shows
"Copied" for ~1.2 s, or "Copy failed".

## Acceptance / Verification
- [x] Copy on user, librarian and persona bubbles copies exactly that message.
- [x] Works after reload (bubbles are re-rendered from storage).

## Status log
- 2026-10-28 — created from the owner's steer.
- 2026-10-28 18:04 — implemented and verified: headless Chrome over CDP (ll_uitest.mjs, 18/18 checks, 0 page errors).
