# F00002 — Slash menu with filtering and autocomplete

| Field | Value |
|-------|-------|
| State | Planned |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | pending |
| Owner | arcane dealer + Grok Bot |
| Class | ux |
| Lineage | Owner brief 2026-10-28, item 2 ("if someone presses slash, it shows a list of the commands and filters based on what they are typing") |
| Depends on | F00001 (menu rows reuse the token colors) |
| Components | `src/neuron_steer/static/index.html` (command registry `COMMANDS`, menu, key handling) |

## Summary
Pressing `/` in an empty compose box opens a command palette above it listing every command with
its signature and a one-line description. It filters as you type (prefix first, then substring),
and you can complete with Tab/Enter or click — or ignore it and keep typing.

## Motivation
Discoverability. New users should never need `/help` to find out what the Library can do.

## Design
* A single registry `COMMANDS = [{name, args, desc, example}]` drives the menu, `/help`, and the
  highlighter's known-command list, so they can't drift apart.
* Opens when the text starts with `/` and the caret is still inside the first word; closes on
  space, Esc, blur, or when nothing matches.
* Ranking: exact → prefix → substring of name → substring of description.
* After a command is completed, a ghost hint shows its argument signature (e.g. `L:N[:up|down] [--alpha X]`).

## UX spec
| key | action |
|---|---|
| `/` | open the menu (all commands) |
| type | filter |
| ↑ / ↓ | move the selection (history recall is suspended while the menu is open) |
| Tab, Enter | complete the selected command + a space (Enter sends instead when what you typed is already a complete command with arguments) |
| Esc | close the menu, keep the text |
| click | complete that command |

## Acceptance / Verification
- [ ] `/` opens a list of all commands; `/ch` narrows to `/checkout` `/checkin`.
- [ ] ↑/↓ + Tab completes; Enter completes; Esc closes; click completes.
- [ ] Once completed, the argument hint shows; Enter then sends normally.
- [ ] Plain chat (no leading slash) never opens the menu; ↑/↓ history recall still works.

## Open questions / follow-ups
- Argument-level completion (neuron specs from the catalogue, persona names for `/checkout`).

## Status log
- 2026-10-28 — created from the owner's brief.
