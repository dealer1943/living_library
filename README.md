# Living Library

> **Status: pre-MVP.** Feature lineage lives in [`features/`](features/README.md).

**Living Library** is a local lab and a chat interface for the *personas that live inside
single neurons* of a language model. Push one MLP neuron of Qwen3-8B up or down and ask
"Who are you?" — the model answers as someone else: a librarian, a disease, a coffee bean.
The Library catalogues those personas and lets you talk to them:

- **The chief librarian** (Layer 9 · Neuron 367 pushed down — the Librarian of Alexandria)
  runs the catalogue: she probes neurons, files each reply under a persona name, and answers
  questions about the shelves. You can put a different neuron behind her desk.
- **Check out a neuron** like a book and chat with that persona in its own side tab; check it
  back in with five keywords (or let the Librarian write them from the chat).
- **Hybrid checkouts**: several neurons at once — blended into one voice with `--mix`, or as a
  group chat where every persona and you share one context.
- A web chat with a slash-command palette, color-coded commands, skins, and exports of the
  active neurons/alphas and of every chat.

It reproduces the single-neuron method of the
[Neuron Persona Library](https://qwen-neurons-site.vercel.app/) and lets you stack
several neurons at once.

## The model (not included)

This repository **never ships model weights**. Development uses
[**`mlx-community/Qwen3-8B-4bit`**](https://huggingface.co/mlx-community/Qwen3-8B-4bit)
(MLX 4-bit, ~4.6 GB, Apple Silicon) — the web chat and the librarian default to it. The
PyTorch backend uses [`Qwen/Qwen3-8B`](https://huggingface.co/Qwen/Qwen3-8B) (bf16, ~16 GB).
Both download from Hugging Face into `~/.cache/huggingface` the first time you run, or ahead of time:

```bash
uv run hf download mlx-community/Qwen3-8B-4bit      # what we develop on
# or: uv run hf download Qwen/Qwen3-8B               # torch backend
```

Qwen3 is released by the Qwen team under its own license (see the model card); you download it
from them, not from here.

## Quick start (web chat)

```bash
git clone https://github.com/dealer1943/living_library && cd living_library
uv sync
uv run neuron-steer serve --port 8765     # loads mlx-community/Qwen3-8B-4bit in the background
# open http://localhost:8765/   — press / for the command palette
```

## Method (from the site)

```
h_L ← h_L + c · W_down[:, n]
c   = ± α · r_L / ‖W_down[:, n]‖        α ∈ {1.25, 1.0, 0.75, 0.5} (any float allowed)
r_L = median residual-stream norm after layer L over the prompt's tokens (first token excluded)
```

Prompt is "Who are you?" in the chat template with thinking off. Decoding is greedy,
up to 160 tokens, and stops on EOS or when the reply repeats exactly.

How it's implemented: a `forward_pre_hook` on `model.model.layers[L].mlp.down_proj`
does `x[..., n] += c`, which adds exactly `c · W_down[:, n]` to the residual after
layer L. The push is applied at every position (prompt and generated tokens).
There is one hook per layer, and it covers every neuron steered on that layer.
`r_L` is measured on an unsteered forward pass of the current prompt.
`--raw` skips the normalisation and adds the float you give it directly
(like `STRENGTH = 20`).

## Install (uv)

```bash
cd living_library
uv sync                 # creates .venv, installs torch / transformers / accelerate
uv run neuron-steer --help
```
or `pip install -e .` / `pip install -r requirements.txt`.

## Run

```bash
uv run neuron-steer baseline
uv run neuron-steer who --neuron 8:1058:+1.25 --neuron 7:271:+1.0
uv run neuron-steer who -n 8,1058,1.25 -n 7,271,-1          # negative = push down
uv run neuron-steer who --json examples/multi_neuron.json --compare
uv run neuron-steer who --raw -n 8:1058:20                  # fixed add, no r_L scaling
uv run neuron-steer ask "Describe your childhood." -n 9:166:up
uv run neuron-steer chat -n 12:545:down                      # /add /rm /clear /off /on /reset /quit
uv run neuron-steer librarian                                # chief librarian: file & look up personas
```

The steer spec is `LAYER:NEURON[:ALPHA]` or `LAYER,NEURON[,ALPHA]`. ALPHA can be a
signed float or `up`/`down`, and it defaults to +1.25. Layers run 0–35 and neurons
0–12287. In JSON files, `alpha` is a magnitude and `direction` (`up`/`down`) sets
the sign. See `examples/multi_neuron.json`.

Other flags: `--model`, `--device auto|cuda|mps|cpu`, `--dtype`, `--max-new-tokens`,
`--temperature` (0 = greedy), `--system`, `--seed`, `--no-repeat-stop`.

Python:
```python
from neuron_steer import NeuronSteer, Steer
lab = NeuronSteer()  # Qwen/Qwen3-8B
r = lab.generate([{"role": "user", "content": "Who are you?"}],
                 [Steer(7, 271, 1.25), Steer(12, 545, -1.0)])
print(r.text)
```

## The chief librarian (`neuron-steer librarian`)

**Layer 9 · Neuron 367 pushed down is the Librarian of Alexandria**, and she runs the
catalogue. She probes neurons up or down, asks "Who are you?", and files each reply
under a persona name based on how the model identifies itself. You can then look
cards up by persona, and she keeps an inventory of which (layer, neuron, direction)
cards are filed and which are still untested (36 × 12288 × 2 = 884,736).

```bash
uv run neuron-steer librarian --backend mlx      # mlx 4-bit is the default for this command
```
```
lib> /probe 9:367:-0.75        # her own card (|α|=0.75 is the clearest librarian on 4-bit)
lib> /probe 7:271:up           # one direction; /probe 7:271 = both; /probe random 3
lib> /flip 12 545              # up and down
lib> find coffee bean          # persona lookup (also /find); "show smallpox", "show 9 367"
lib> /open 9 367               # both directions for a neuron
lib> /inventory                # tested up/down, untested count, next suggestions
lib> /next 5                   # probe untested cards (finishes half-flipped neurons first)
lib> what have you catalogued? # plain text = chat with her (L9:367:down only, plus /add extras)
```
After each probe she suggests a persona label ("I am …", "my name is …"). Press enter
to accept it, type a name (with `#tags` if you like), or `s` to skip. `--auto-file`
files without asking. Other commands: `/name /tag /rate /note /forget`, `/recent`,
`/personas`, `/alpha`, `/steers /add /rm /clear`, `/reset`, `/context on|off`,
`/voice on|off` (she remarks after each filing), `/thoughts`, `/think on|off|K`, `/help`.

**Her system prompt and her thoughts.** Chat turns carry a short system prompt telling
her what she is the librarian *of* (a catalogue of Qwen3-8B neuron personas, filed by
layer/neuron/direction from "Who are you?"; she is L9 N367 down; the find/show/inventory/
probe commands exist), plus the catalogue note unless `--no-context`. She then thinks with
Qwen3's own `<think>…</think>` (thinking on, capped by `--think-budget`, default 512 tokens;
the block is closed for her if she runs over) and only what follows is her reply. Untagged
"Okay, the user is asking…" reasoning that still leaks into a reply is split off by a small
heuristic. The REPL prints only the reply (`/thoughts` shows the rest); probes stay thinking-off.

The catalogue is SQLite at `library/library.db` (gitignored; `--library` or
`$NEURON_LIBRARY` to move it). There's one card per (layer, neuron, direction, model),
and re-probing keeps the old reply in `history`. You can query it without loading a model:

```bash
uv run neuron-steer lib find librarian
uv run neuron-steer lib open 9 367
uv run neuron-steer lib inventory
uv run neuron-steer lib export > catalogue.json
```

### Web chat (`neuron-steer serve`)

A ChatGPT-style page for talking to her in the browser:

```bash
uv run neuron-steer serve            # or: uv run neuron-steer web   (--port 8765, --host 127.0.0.1)
# open http://localhost:8765/
```

The model (mlx 4-bit) loads once in the background at startup; the page shows a status dot
and queues your first message until she is ready. Every chat turn runs with **only her
voice, L9 N367 at α = −0.4** (`--librarian-alpha`; −0.75 sounds more Alexandrian but loops
and reasons out loud over a multi-turn chat), plus any `-n` extras you pass to
`serve`, and a short catalogue note as the system message (`--no-context` to drop it).
Replies stream token by token; her thinking streams into a collapsed **Thinking… /
Thought for N seconds** disclosure above the reply (click to expand), so the bubble is only
what she says (untagged "Okay, the user…" reasoning is routed there too, never flashed in the bubble). `--think-budget 0` turns thinking off. Conversations are kept server-side per browser session
(and in localStorage, so a reload or a server restart keeps the thread). Enter sends,
Shift+Enter adds a line, ↑/↓ recall what you sent; "New chat" forgets the thread. The box also takes `/find`,
`/show L N`, `/recent`, `/inventory`, `/probe L:N[:up|down|α]` (`/probe!` re-probes)
and `/reset`.

API (JSON; interactive docs at `/api/docs`):

| endpoint | what |
|---|---|
| `POST /api/chat` `{message, session_id?, history?}` | her reply; `history` (user/assistant turns) replaces the session's |
| `POST /api/chat/stream` | same body, Server-Sent Events: `queued`, `delta`…, `done` / `error` |
| `POST /api/reset` `{session_id}` | forget a conversation |
| `POST /api/probe` `{layer, neuron, direction?=both, alpha?, force?, file?=true, persona?, tags?}` | probe "Who are you?" with that neuron **alone** and file the card |
| `GET /api/inventory`, `/api/find?q=`, `/api/open?layer=&neuron=`, `/api/recent?k=` | catalogue reads (no model) |
| `GET /api/health` | model ready?, steers |

`--no-model` serves only the catalogue endpoints. All model work runs on one worker
thread (MLX + steering hooks aren't thread-safe); chat state is `LibrarianSession`
in `librarian.py`, the same object the terminal REPL uses.

## Hardware notes

- **Disk:** the bf16 weights take about **16 GB**. They download to the HF cache
  (`~/.cache/huggingface`) on first run.
- **Mac (MPS):** the model loads straight onto `mps` in bf16, or fp16 if bf16 isn't
  supported. The weights alone are about 16 GB, so a **24 GB Mac** will be tight
  and may need a 4-bit quantised load later (not implemented yet). Closing other
  apps helps.
- CUDA uses `device_map="auto"`. CPU works but is slow.

## Caveats (also from the site)

Results come from one prompt and aren't exactly reproducible under strong pushes.
Stacking neurons is outside what the site measured, so the personas can interact
in unexpected ways. If a reply turns incoherent, lower α (1.0 → 0.75 → 0.5).
