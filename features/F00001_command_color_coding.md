# F00001 — Color-coded commands and parameters

| Field | Value |
|-------|-------|
| State | Planned |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | pending |
| Owner | arcane dealer + Grok Bot |
| Class | ux |
| Lineage | Owner brief 2026-10-28, item 1 ("color code any commands or parameters so they stand out from text") |
| Depends on | — |
| Components | `src/neuron_steer/static/index.html` (highlighter, input overlay, skin token colors) |

## Summary
Every slash command, flag and parameter is colored so it stands out from prose: in the
compose box *while typing*, in your sent command bubbles, in catalogue (system) output, in
`/help`, in the footer hint, and when the Librarian or a persona mentions a command in a reply.

## Motivation
The chat mixes conversation with a command language (`/probe 12:545:up --alpha 0.5 --prompt "…"`).
Without color the two blur together; with it, the grammar teaches itself at a glance.

## Design
One tokenizer (`highlight(text, {cmd})`) emits escaped HTML spans:

| token | examples | class |
|---|---|---|
| command | `/probe`, `/probe!`, `/checkout`, `find` (REPL shortcut at line start) | `tok-cmd` |
| flag | `--alpha`, `-a`, `--mix`, `--prompt`, `alpha=` | `tok-flag` |
| neuron spec | `12:545:up`, `9:367:down:0.4`, `L12 N545`, `L9:N367` | `tok-neuron` |
| direction | `up`, `down` (inside a command) | `tok-dir` |
| number / α | `0.5`, `-0.4`, `α=-0.4` | `tok-num` |
| quoted string | `"what is your story?"` | `tok-str` |

* Commands are only colored when they are known commands (prose like "and/or" stays plain).
* In free prose (assistant replies) only commands, flags and neuron specs are colored; numbers stay plain.
* The compose box uses a mirrored overlay behind a transparent-text `<textarea>` so typing stays native
  (caret, selection, IME, undo) while the text appears colored.
* Colors are CSS variables per skin (F00009) so every theme keeps contrast.

## UX spec
Type `/probe 12:545 --alpha 0.5` → `/probe` gold, `12:545` teal, `--alpha` violet, `0.5` orange, live.

## Acceptance / Verification
- [ ] Typing a command in the box colors it live; caret position and wrapping line up with the text.
- [ ] Sent command bubbles, system output, `/help`, hint bar are colored.
- [ ] A reply that mentions `/probe 12:545:up` shows it colored; ordinary prose is untouched.
- [ ] No HTML injection (text is escaped before spans are added).

## Open questions / follow-ups
- Color-blind-safe palette as a skin variant.

## Status log
- 2026-10-28 — created from the owner's brief.
