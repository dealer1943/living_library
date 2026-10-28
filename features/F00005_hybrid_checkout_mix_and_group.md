# F00005 — Hybrid checkout: `--mix` blend or group chat

| Field | Value |
|-------|-------|
| State | Planned |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | pending |
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

## Acceptance / Verification
- [ ] `/checkout A B --mix` → one tab, header lists both steers, reply generated with both pushes.
- [ ] `/checkout A B` → group tab; one message gets one reply from each persona, in order, each named.
- [ ] Second round: personas can refer to each other's previous lines (shared context).

## Open questions / follow-ups
- Mention a member (`@emily`) to have only them answer; turn order shuffle; per-member α sliders.

## Status log
- 2026-10-28 — created from the owner's brief.
