# F00008 — Settings: export active neurons + alphas, and chats

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 14:21 America/New_York — headless Chrome (f8.js): Settings → Export downloaded neurons JSON (Librarian L12 N545 +0.6, smallpox +1.0, group +1.0/−0.75), chats JSON (3 tabs, 11 messages) and Markdown; /export chats md downloaded too; the file and each tab block load with neuron_steer.steer.load_steers_json |
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

## As built (2026-10-28)
* Settings → **Export** shows a live summary (Librarian + each tab with signed α, neuron count, chats and
  messages) and three buttons: *Active neurons · JSON*, *Chats · JSON*, *Chats · Markdown*. Also
  `/export neurons`, `/export chats`, `/export chats md`.
* `living-library-neurons-<ts>.json` = `{format: "living-library/neurons@1", model, steers: [every
  active neuron, de-duplicated], librarian: {name, default, steers}, tabs: [{name, kind, checked_out_at,
  steers}]}`; each steer is `{layer, neuron, alpha (signed), direction, name}`. The whole file and each
  tab block load with `load_steers_json` (what `neuron-steer who --json` uses).
* Chats JSON = every open tab + the checked-in shelf (with keywords and their source), each message
  `{role, speaker, command, content, thoughts?, steers?, meta?, at}`. Markdown = one section per tab,
  thoughts in `<details>`, catalogue notes as code blocks.

## Acceptance / Verification
- [x] Neurons export lists the Librarian + all open tabs with correct signed alphas.
- [x] Chats JSON contains every tab's messages; Markdown is readable.
- [x] A neurons export tab block is accepted by `neuron-steer who --json`.

## Status log
- 2026-10-28 — created from the owner's brief.
- 2026-10-28 14:21 — implemented and verified: headless Chrome (f8.js): Settings → Export downloaded neurons JSON (Librarian L12 N545 +0.6, smallpox +1.0, group +1.0/−0.75), chats JSON (3 tabs, 11 messages) and Markdown; /export chats md downloaded too; the file and each tab block load with neuron_steer.steer.load_steers_json
