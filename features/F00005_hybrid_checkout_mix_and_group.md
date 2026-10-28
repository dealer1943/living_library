# F00005 — Hybrid checkout: `--mix` blend or group chat

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 14:21 America/New_York — headless Chrome: '/checkout emily + smallpox --mix' → one tab, mode=mix with 2 members, reply meta 'L12 N545 α=+1 + L7 N271 α=+1'; '/checkout emily + smallpox' and '/checkout emily + 9:367:down:0.75' → group tabs where one message got a named, colored reply from each member in order (f345.js, f8.js) |
| Owner | arcane dealer + Grok Bot |
| Class | persona |
| Lineage | Owner brief 2026-10-28, item 5 (check out more than one persona; `--mix` = one blended persona; without it = group chat with all personas + user in one context) |
| Depends on | F00003, F00004 |
| Components | `web.py` (`/api/checkout`, `/api/persona/stream`), `static/index.html` |

## Summary
`/checkout` takes several neurons at once.
* **With `--mix`**: one tab, one voice — every listed neuron is pushed *simultaneously* on each
  token (the multi-neuron stack the project was built on), so the reply is a blend.
* **Without `--mix`**: a group-chat tab. Each persona is its own voice; when you send a message
  they answer one after another, every one seeing the whole shared transcript (you + all of them).

## Design
* Syntax: `/checkout 12:545:up 7:271:down [--mix] [--alpha X]`, per-neuron α as `12:545:up:0.6`;
  persona names joined with `+`: `/checkout smallpox + emily --mix`.
* Mix: steers = all members; name `Mix: A × B`. α per member as given (no automatic rescaling;
  lower α if the blend turns incoherent — stacking is outside what the original site measured).
* Group: server turns the shared transcript into a chat for the current speaker: its own past
  lines are `assistant`, everyone else's (user + other personas) are merged `user` turns prefixed
  `Name:`; a short system line tells it who is in the room. Each turn uses only that member's steer.
  The page streams members in order into separately-colored, named bubbles.
* Check-in of a mix/group logs every member (F00003) with the shared keywords.

## As built (2026-10-28)
* `/checkout emily + smallpox --mix` → `kind: mix`, one voice generated with every member's steer at
  once (α not rescaled); header and tab say `mix · L12N545+L7N271`.
* `/checkout emily + smallpox` (also `;` or repeated specs) → `kind: group`: each of your messages is
  answered by every member **in order**, each seeing the whole shared transcript (its own lines as
  assistant turns, everyone else's as `Name: …` user lines, plus a short room system line and a
  "your turn" cue). Bubbles are named and colored per member. A reply that only parrots an earlier line
  is regenerated once; a leading `Name:` echo is stripped.
* Members can be mixed forms: `/checkout emily + 9:367:down:0.75`. Duplicate names get `(L N)` suffixes.

## Acceptance / Verification
- [x] `/checkout A B --mix` → one tab, header lists both steers, reply generated with both pushes.
- [x] `/checkout A B` → group tab; one message gets one reply from each persona, in order, each named.
- [x] Second round: personas can refer to each other's previous lines (shared context). *(verified structurally: each member's request carries every other member's lines as `Name: …`; how well they actually respond to each other at α ≈ 1 is weak — see follow-ups)*

## Open questions / follow-ups
- Mention a member (`@emily`) to have only them answer; turn order shuffle; per-member α sliders.
- Group coherence is weak at α ≈ 1 (members talk about the *names*, or reason aloud). Lower α per member
  (`/alpha emily 0.7`) helps; a smarter turn order (who was addressed) is a post-MVP idea.

## Status log
- 2026-10-28 — created from the owner's brief.
- 2026-10-28 14:21 — implemented and verified: headless Chrome: '/checkout emily + smallpox --mix' → one tab, mode=mix with 2 members, reply meta 'L12 N545 α=+1 + L7 N271 α=+1'; '/checkout emily + smallpox' and '/checkout emily + 9:367:down:0.75' → group tabs where one message got a named, colored reply from each member in order (f345.js, f8.js)
