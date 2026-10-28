# F00013 — Continue replies cut at the token limit (new bubble)

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 18:04 America/New_York — curl: a persona at `max_new_tokens 40` returned `truncated: true`, and `continue_text` produced the seamless next 40 tokens ("…his" → "days marked by the rhythmic crash of waves…", joiner " "); librarian `/api/chat/stream` continue OK. headless Chrome over CDP (ll_uitest.mjs, 18/18 checks, 0 page errors): a cut bubble showed ▸ Continue, clicking it streamed into a new bubble marked "continued", and the model's history merged both parts into one turn |
| Owner | arcane dealer + Grok Bot |
| Class | ux / infra |
| Lineage | Owner steer 2026-10-28: a reply stopped at ~598 tokens (≈200 think + the 400-token reply cap); "continue in a new bubble rather than silently truncating" |
| Depends on | F00003 |
| Components | `steer.py` (`GenerationResult.truncated`), `mlx_steer.py` (`assistant_prefix`), `librarian.py`, `web.py` (`continue_text`, `_continuation`), `static/index.html` (`continueFrom`, `mergedTurns`, `keepPartial`) |

## Summary
When a reply hits `max_new_tokens`, it is no longer silently cut off: the page carries on
**automatically in a fresh bubble** in the same tab, as many as 3 times. If it is still unfinished, or a stream
broke mid-reply (server restart, network), the partial text is kept and the bubble gets a
**▸ Continue** button.

## Design
- `done.truncated` = the reply used all `max_new_tokens` and didn't stop on EOS or a repeat.
- `continue_text` on `/api/chat/stream` and `/api/persona/stream` re-encodes the same conversation and
  places the text so far **after the assistant prompt** (thinking off), so the model resumes
  mid-sentence with the same steers. The reply is streamed raw (no reasoning split on a fragment) and
  returned with `continued: true` and a `joiner` (the leading whitespace).
- Client: parts are stored as separate messages (`cont: true`, `join`) and `mergedTurns` merges
  them back into one assistant turn for the librarian history and the persona transcript.
- Group chats finish the current speaker before the next one speaks.

## UX spec
Cut bubble meta: "… · token limit" → "… · continued ↓"; the new bubble's meta starts with "continued".
An interrupted bubble reads "interrupted", and an error note says that ▸ Continue picks up from there.

## Acceptance / Verification
- [x] Token-limit stop auto-continues into a new bubble (librarian + persona, all modes).
- [x] Interrupted streams keep their text and offer ▸ Continue.
- [x] Model history sees one merged reply, not fragments.

## Status log
- 2026-10-28 — created from the owner's steer.
- 2026-10-28 18:04 — implemented and verified (curl + headless Chrome, see Verified).
