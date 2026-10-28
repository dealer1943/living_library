# F00008 — Settings: export active neurons + alphas, and chats

| Field | Value |
|-------|-------|
| State | Planned |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | pending |
| Owner | arcane dealer + Grok Bot |
| Class | export |
| Lineage | Owner brief 2026-10-28, item 8 ("export the active neurons and alphas associated … export the actual chats too") |
| Depends on | F00004, F00007 |
| Components | `static/index.html` (export section, `/export`) |

## Summary
Settings → Export downloads:
* **Active neurons** (`living-library-neurons-<ts>.json`): the Librarian's voice plus every
  checked-out tab with mode and each member's layer, neuron, direction, signed α — in the same
  shape as `examples/multi_neuron.json` (`{"steers":[{layer, neuron, alpha, direction}]}`) per tab,
  so it can be fed back to `neuron-steer who --json`.
* **Chats** as JSON (all tabs, every message with speaker, timestamp, thoughts) or Markdown
  (readable transcript per tab).
Commands: `/export neurons`, `/export chats`, `/export chats md`.

## Acceptance / Verification
- [ ] Neurons export lists the Librarian + all open tabs with correct signed alphas.
- [ ] Chats JSON contains every tab's messages; Markdown is readable.
- [ ] A neurons export tab block is accepted by `neuron-steer who --json`.

## Status log
- 2026-10-28 — created from the owner's brief.
