# F00015 — About room: the Librarian teaches the neuron process from ground zero (8B or 27B teacher)

| Field | Value |
|-------|-------|
| State | Verified |
| Stage | pre-MVP |
| Created | 2026-10-29 |
| Verified | 2026-10-29 19:29 America/New_York — owner browser verify: the Librarian explained neurons, layers and α in the About room |
| Owner | arcane dealer + Grok Bot |
| Class | ux / persona / infra |
| Lineage | Owner brief 2026-10-29: an About button top right; a dedicated chat where the librarian educates and answers questions about the neuron process (what α does, what neurons do, what layers mean) so someone can learn from ground zero; a system prompt and/or a detailed doc she sources; credit Josh (@jfonsecarivera, [post](https://x.com/jfonsecarivera/status/2115109334090920065)), who did this on the 8B; let the user pick the 8B or the "twenty-something" model we have (Ternary Bonsai 2 27B) |
| Depends on | F00004, F00013 |
| Components | `docs/neuron_primer.md` (new); `src/neuron_steer/about.py` (new: `MODELS`, `TEACH_PROMPT`, `KEY_FACTS`, `load_cards`, `select_cards`, `teach_system`, `Bonsai`); `web.py` (`about_sync`, `about_model`, `models_info`, `POST /api/about/stream`, `GET /api/models`, `POST /api/models/start\|stop`, health `about`); `cli.py` (`--about-model`, `--about-alpha`, `--about-max-tokens`, `--primer`, `--bonsai-url`, `--bonsai-dir`); `static/index.html` (`#about-btn`, `openAbout`, `aboutEmpty`, `sendAbout`, `teacherHTML`, `refreshModels`, `bonsaiAction`, `/about`, Settings → Models); `README.md` (Credits, About room, API, hardware) |

## Summary
An **About** button at the far top right opens a fixed **About the Library** tab where the chief librarian
teaches how the lab works — layers, neurons, up vs down, α, "Who are you?", personas, the shelf, the Lounge —
from first principles, and answers follow-up questions. Answers are grounded in a written primer,
`docs/neuron_primer.md`, whose matching sections are put in the system prompt each turn. The teacher can be
**Qwen3-8B** (default, in her steered voice) or **Ternary Bonsai 2 27B** (larger, unsteered, chat-only), picked
in the room's header, in Settings, or with `/about 8b|27b`. The README now credits Josh and his atlas.

## Motivation
The librarian runs the catalogue but had no idea what α, neurons or layers were; a newcomer had nowhere to
learn. A primer keeps the facts exact (every number in it comes from the code or Josh's site) and editable
without touching prompts, and a room keeps teaching out of the desk's catalogue context.

## Design
- **Primer** `docs/neuron_primer.md`: ~2.3k words in `##` cards, each with `<!-- keywords: … -->`; one card is
  `<!-- core -->` (what the lab is, Josh's atlas). Cards: model shape (36 layers × 12,288 neurons, hidden 4096,
  884,736 cards), layers/residual stream, what a neuron is, up vs down, α formula
  (`c = ±α·r_L/‖W_down[:,n]‖`, r_L = median residual norm after layer L), α values (probe 1.25, retries 1.0 →
  0.75 → 0.5, chat 1.0 / cap 1.0, librarian 0.4 down, UI 0 < |α| ≤ 3), the probe, personas, the shelf, the
  Lounge, the librarian and thinking, models 8B vs 27B, tips, limits. Reloaded when its mtime changes.
- **Retrieval** (`select_cards`): core card + up to 3 best keyword matches over the last 2 user messages
  (3·keyword + 2·title + body hits; a card needs score ≥ 3 and ≥ ⅓ of the top), budget ~1,100 words; no
  match → layer/neuron/α cards. `done.cards` reports which cards were used (shown under each reply).
- **System prompt**: `TEACH_PROMPT` (answer only from the primer, plain words first then precise, short, end
  with one command to try, credit Josh) + voice line + `KEY_FACTS` (the facts the 8B swapped in testing:
  librarian = 9:367 down, emily = 12:545 up, `/alpha X` takes no direction, α defaults, model shape) + cards.
  History: last 8 turns.
- **8B teacher** (`qwen3-8b`, `mlx-community/Qwen3-8B-4bit`): the already-loaded model, her voice at a
  lighter push (L9 N367 down, α −0.2 via `--about-alpha 0.2`; at the desk's 0.4 the 8B swapped up/down
  facts in testing, at 0.2 and 0 it got them right; `0` = plain Qwen3-8B), greedy, thinking budget as the desk,
  600 new tokens (`--about-max-tokens`), auto-continue (F00013).
- **27B teacher** (`bonsai-27b`, `prism-ml/Ternary-Bonsai-2-27B-gguf`, PQ2_0 ~7.2 GB): `Bonsai` wraps Prism's
  `llama-server` (`-ngl 99 -fa on -c 16384 --jinja --temp 1.0 --top-p 0.95 --top-k 20`, log at
  `$TMPDIR/living-library-bonsai.log`), started/stopped on demand (`POST /api/models/start|stop`), or an
  already-running server at `--bonsai-url`. Streams OpenAI SSE (`reasoning_content` → Thoughts). Unsteerable
  (rotated ternary basis), so it teaches unsteered and never probes.
- **API**: `POST /api/about/stream {message, history, model?, continue_text?, voice_alpha?}` → the usual
  `text` / `thought` / `done` / `error` SSE events; `GET /api/models` → `{default, models:[{id, label, hf_id,
  steerable, state}]}`; health gains `about`.

## UX spec
- **About** button, far right of the header (after ⚙). In the room it reads **← Back** and returns to the tab you came from.
- Empty room: intro, Josh credit (links to his post and atlas), the **Teacher** picker (Qwen3-8B · Bonsai 27B,
  with state; **Start 27B** / **Stop 27B**), and 8 starter questions (click to ask).
- Enter sends, Shift+Enter newline; thoughts collapse; Copy / Share / Continue work as in other tabs. Each
  reply's meta shows the teacher and the primer cards used. `/alpha` here explains it is for persona tabs.
- `/about` (alias `/learn`) opens the room; `/about 27b` / `/about 8b` also switch the teacher. The choice
  persists (`prefs.aboutModel`); Settings → Models shows the same picker.
- If the 27B is chosen but not running, the reply bubble says so and offers Start 27B.

## Acceptance / Verification
- [x] About button sits top right; opens the About tab; ← Back returns to the previous tab.
- [x] Starter "What does α do?" gets a correct, primer-grounded answer on the 8B (α 1.25 probe / 1.0 chat / 0.4 librarian; `/alpha X` without a direction).
- [ ] "Who is the chief librarian, as a neuron?" → layer 9, neuron 367, down.
- [ ] Teacher picker switches to Bonsai 27B; Start 27B launches it (~10–20 s); an answer streams with Thoughts.
- [ ] `/about 27b`, `/about 8b` switch the teacher; the choice survives reload.
- [x] README credits Josh (@jfonsecarivera, post link, quote, atlas link, his 8B success).
- [ ] Other tabs (desk, personas, Lounge) unchanged.

## Open questions / follow-ups
- The 8B is a small teacher: even grounded, it can paraphrase loosely; `KEY_FACTS` fixes the errors seen in
  testing, more may surface. Answers take ~25–35 s with thinking on. The 27B is more fluent but ~30 s per
  answer and needs ~7 GB more memory.
- Could add a "read the primer" link/drawer in the room, and embeddings instead of keyword retrieval.

## Status log
- 2026-10-29 — created and implemented (primer, about.py, endpoints, UI, README credit). Headless-Chrome check
  of button/tab/picker/commands; 8B answers via curl on :8765; Bonsai 27B start → answer → stop on a test port.
  Awaiting owner browser verification; not committed.
- 2026-10-29 — Verified 2026-10-29 19:29 America/New_York by owner in the browser (About room: the librarian explained neurons, layers and α). Committed.
