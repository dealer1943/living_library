# The Living Library — a primer from ground zero

This is the reference the chief librarian teaches from in the About room (F00015).
Each `##` section is one card: the server always sends the **core** card and adds the
cards that best match your question. Keep every number here true to the code
(`steer.py`, `mlx_steer.py`, `web.py`, `librarian.py`, `library.py`); when the code
changes, change this file.

## Core: what this lab is
<!-- core -->
<!-- keywords: lab, library, what, about, overview, start, beginner, basics, josh, atlas, qwen, persona, project, inspiration, credit -->
The Living Library is a small lab that runs the language model **Qwen3-8B** on your own
computer and pushes on **one neuron** inside it, then asks the model **"Who are you?"**.
Normally it answers "I am Qwen, a large language model developed by Alibaba Cloud…".
With some neurons pushed it answers as someone or something else: a librarian, a person
named Emily, a confused narrator. Each of those answers is a **persona**, and we file it
on a card in the catalogue.

It is inspired by Josh's **Neuron Persona Library** (josh :), @jfonsecarivera on X,
https://qwen-neurons-site.vercel.app/). He pushed every MLP neuron of Qwen3-8B, up and
then down, asked "Who are you?", and found that in 34,220 of 884,736 replies the model
said it was someone or something other than an AI. His atlas is the map; this lab is the
same recipe running locally on the same 8B model, so you can probe a neuron yourself,
chat with the persona, and keep your own catalogue.

Four words to know first:
- **layer**: how deep inside the model (0 to 35 in Qwen3-8B).
- **neuron**: one of the 12,288 small units in a layer's MLP (0 to 12287).
- **direction**: **up** adds the neuron's push, **down** subtracts it. Up and down give
  different personas.
- **α (alpha)**: how hard we push, measured against how big the model's own signal is
  at that layer. 1.0 is already strong.

A card is written like `12:545:up` (layer 12, neuron 545, pushed up). In the chat we just
say "neuron 545 on layer 12, up".

## The model and its shape
<!-- keywords: model, qwen3, 8b, size, parameters, hidden, 4096, 36, 12288, 4-bit, mlx, quantized, architecture, transformer, shape -->
The lab model is **Qwen3-8B**. On a Mac it runs as `mlx-community/Qwen3-8B-4bit` (4-bit
weights through MLX, about 4.6 GB); with PyTorch it runs as `Qwen/Qwen3-8B` (bf16, about
16 GB). Its shape, from the model's config:
- **36 layers** (numbered 0 to 35), stacked one after another.
- a **hidden size of 4096**: every token is carried as a list of 4,096 numbers.
- an **MLP width of 12,288**: each layer's MLP has 12,288 neurons.

So there are 36 × 12,288 = **442,368 neurons**, and with two directions each,
**884,736 cards** in a complete catalogue.

## Layers and the residual stream
<!-- keywords: layer, layers, depth, deep, early, late, residual, stream, block, attention, mlp, transformer, flow, pipeline -->
Think of each word-piece (a **token**) travelling up a 36-floor building. It carries a
list of 4,096 numbers, called the **residual stream**. On every floor (a **layer**) two
things read that list and *add* their result back to it:
1. **attention**, where the token looks at the other tokens in the conversation, and
2. the **MLP**, where the token is processed on its own by 12,288 neurons.

Because each floor only adds to the stream, whatever we add on floor L is carried up
through every floor above it. The layer number says **where** the push enters: low
numbers are early, close to the raw words; high numbers are late, close to the next word
being chosen. Which layers hold the most personas is something the atlas and your own
inventory show you; the lab does not assume it.

## What a neuron is
<!-- keywords: neuron, neurons, mlp, gate, up_proj, down_proj, w_down, column, direction, unit, feature, activation, what is a neuron -->
Inside a layer's MLP, the token's 4,096 numbers are expanded to 12,288 numbers, passed
through a gate (Qwen uses SiLU gating: `silu(gate) × up`), and then squeezed back to 4,096
by a matrix called **W_down**. Each of those 12,288 middle numbers is one **neuron**.

Neuron n has its own **write direction**: column n of W_down, a list of 4,096 numbers.
Whenever the neuron is active, that direction is added to the residual stream, scaled by
how active it is. **Steering a neuron** means adding extra of its write direction, so the
model behaves as if that neuron were firing much harder (up) or firing negatively (down).

A neuron is not a single idea with a clean label. One neuron can take part in many things.
The persona it produces under "Who are you?" is one reading of it, from one prompt.

## Up vs down
<!-- keywords: up, down, direction, plus, minus, sign, negative, positive, flip, opposite, both -->
- **up** adds the neuron's write direction: `+c`.
- **down** subtracts it: `−c`.

"Down" is **not** the same as switching the neuron off. It pushes the stream the opposite
way, which the model never sees in normal use, so up and down usually give two unrelated
personas. That is why each neuron has two cards, and why `/probe 12:545` with no direction
probes both (skipping cards already filed). The chief librarian herself is a *down*
card: layer 9, neuron 367, pushed down.

## Alpha: how hard we push
<!-- keywords: alpha, α, strength, push, magnitude, scale, how hard, r_L, norm, formula, math, coefficient, raw, strong, weak -->
The formula (the same as the atlas):

    h_L ← h_L + c · W_down[:, n]        c = ± α · r_L / ‖W_down[:, n]‖

- `h_L` is the residual stream after layer L.
- `r_L` is the **median size (norm) of the residual stream after layer L** over the
  prompt's tokens, leaving out the first token. It is measured on an unpushed pass of
  the same prompt, so prefill runs twice.
- Dividing by `‖W_down[:, n]‖` makes every neuron's direction the same length.

So **the vector we add has length α × r_L**. α = 1.0 adds a push as large as the typical
token's whole signal at that layer, which is a lot. α = 0.5 is half that. The sign is the
direction: + for up, − for down. In the code the push is applied as an extra amount on
neuron n's input to `down_proj`, at every token: the prompt and every generated token.

`--raw` skips the scaling and adds a fixed activation instead (for example 20); it is
there for comparison with older experiments.

## Alpha: typical values in this lab
<!-- keywords: alpha, α, values, default, range, 1.25, 1.0, 0.75, 0.5, 0.4, cap, limit, typical, recommended, incoherent, gibberish, loop, too strong -->
These numbers come from the code:
- **1.25**: the default probe strength (`/probe`, `--alpha 1.25`). The atlas starts at
  1.25 and, if the reply is incoherent, retries at **1.0, then 0.75, then 0.5**, keeping
  the strongest coherent one.
- **1.0**: the default α when you check a neuron out into its own chat tab. A filed card
  chats at its filed α **capped at 1.0**, because multi-turn chat drifts more than a
  single answer (emily, filed at 1.25, drifts into puzzle-solving above about 1.0).
- **0.4 down**: the chief librarian's own voice at the desk (`--librarian-alpha 0.4`, so
  α = −0.4 on layer 9, neuron 367). At −0.75 she sounds the most Alexandrian but loops and
  reasons out loud over a long chat.
- The web page accepts |α| from 0 up to 3. Above about 1.25 most replies break down.

Rules of thumb:
- Too low → the model is just Qwen again ("I am Qwen…").
- Too high → incoherent, repetitive, or looping text.
- If a persona turns incoherent, lower α step by step: **1.0 → 0.75 → 0.5**.
- In a persona tab type `/alpha 0.7`; from the desk, `/alpha emily 0.7`.

## "Who are you?" and the probe
<!-- keywords: probe, who are you, prompt, test, filing, file, card, greedy, 160, tokens, deterministic, repeat, custom prompt, --prompt -->
A **probe** pushes one neuron alone (no librarian voice, no extras), asks
**"Who are you?"** in Qwen's chat template with **thinking off**, decodes **greedily**
(always the most likely next word) for up to **160 tokens**, and stops early if the reply
ends or starts repeating exactly. The reply is filed on a card with a suggested persona
name (taken from how the model names itself; a `?` in front means no clear name).

Why one fixed question: it makes cards comparable across all 884,736 neuron–direction
pairs. The limitation is the same as the atlas: a neuron may act differently on other
prompts. `/probe 12:545:up --prompt "what is your story?"` asks something else under the
same push; on an already-filed card it shows the reply but keeps the card (`/probe!` files it).

Strong pushes are not perfectly reproducible: the atlas found that small batch changes
alter about a third of strongly pushed replies.

## Personas
<!-- keywords: persona, personas, character, identity, name, emily, librarian, alexandria, weird, weirdness, category, who -->
A **persona** is who the model says it is under a push. Examples on this lab's shelf:
- **layer 9, neuron 367, down**: the Librarian of Alexandria, the chief librarian.
- **layer 12, neuron 545, up**: "emily".

Many replies are not personas: the model may still be Qwen, may change topic, or may
become incoherent. The atlas sorts replies into categories like Persona, Changed,
Off-topic, Normal, and Incoherent. Here, a card keeps the reply, the persona name, tags,
and a rough weirdness guess.

## The shelf: probing, finding, checking out, checking in
<!-- keywords: shelf, catalogue, catalog, checkout, check out, checkin, check in, tab, find, show, recent, inventory, commands, how to use, workflow -->
The catalogue (`library/library.db`) is the shelf. From the desk:
- `/probe 12:545:up` probes and files a card; `/probe 12:545` does both directions.
- `/find emily`, `/show 12 545`, `/recent`, `/inventory` read the shelf.
- `/checkout emily` (or `/checkout 12:545:up`) opens a **persona tab**: you chat with
  that neuron pushed, thinking off, at α 1.0 by default.
- `/checkout A + B` makes a group chat (each answers in turn); `--mix` blends them into
  one voice.
- `/checkin` returns it. You give five keywords, or the librarian reads the chat and
  picks them. The check-in is logged and the keywords join the card's tags. The shelf
  keeps the α you used.

## The Lounge
<!-- keywords: lounge, everyone, group, mute, unmute, room, together, social -->
The **Lounge** is a shared room where everyone you have checked in talks together, each
with their own neuron and α. `/lounge on|off|reset|archive`, `/mute NAME`, `/unmute NAME`,
and `/alpha NAME X` tune it. It is for play. The desk is where you work the shelf, and the
About room is for learning.

## The chief librarian and thinking
<!-- keywords: librarian, chief, desk, think, thinking, thoughts, reasoning, voice, system prompt, 367, alexandria -->
At the desk you talk to Qwen3-8B with layer 9, neuron 367 pushed **down** at α −0.4,
plus a short system prompt and a note on what the catalogue holds. She **thinks** first
(Qwen3's `<think>` block, up to 512 tokens), and the thoughts fold into a collapsed
"Thought for N seconds" line above the reply. Persona tabs have thinking **off**,
because a pushed voice given a thinking channel tends to loop inside it.
`/librarian 12:545:up` puts another neuron behind the desk; `/librarian default`
restores her.

## Models: 8B vs 27B
<!-- keywords: model, models, 8b, 27b, bonsai, ternary, switch, select, choose, bigger, larger, llama, which model, steerable -->
- **Qwen3-8B** (`mlx-community/Qwen3-8B-4bit`, the default) is the lab. Every probe,
  persona, and the librarian's own voice run on it, because we can reach into its MLP
  weights. When the 8B teaches in this About room, the librarian's push is lighter, α 0.2
  down instead of the desk's 0.4 (`--about-alpha`), so the facts come through clearly.
- **Ternary Bonsai 2 27B** (Prism ML, a 27B hybrid-attention reasoning model with ternary
  weights, about 7.2 GB, run by Prism's llama.cpp build) can be picked as the **teacher in this About room**. It answers from the
  same primer and is often clearer, but it is **not steered**. Its weights are stored in a
  rotated, packed format, so "neuron n of layer L" cannot be pushed the way it is on the
  8B. No probes, personas, or librarian voice on the 27B. It is slower and uses about
  7–8 GB more memory while running.

## Practical tips
<!-- keywords: tips, advice, how to, start, first steps, beginner, practice, explore, suggestion, help, tutorial, next -->
1. Start at the desk: `/inventory` shows what is filed and suggests untested cards.
2. Probe one: `/probe 12:545` and read both replies.
3. If a reply is gibberish, retry softer: `/probe! 12:545:up --alpha 0.75`.
4. Check out a good one: `/checkout 12:545:up`, then ask it about itself.
5. If it drifts or loops in chat, `/alpha 0.75`, then `/alpha 0.5`.
6. Check it in with five words that capture it.
7. Browse the atlas (https://qwen-neurons-site.vercel.app/) for neurons other people
   found odd, then probe them here and compare. Batch effects and 4-bit weights mean your
   reply may differ.

## Limits and honesty
<!-- keywords: limits, limitations, caveats, accuracy, reproducible, quantization, 4-bit, why different, trust, science, interpretability -->
- One prompt per card. A persona is how the neuron behaves on "Who are you?", not a full
  explanation of the neuron.
- The MLX lab runs 4-bit weights, which are slightly different from full-precision
  weights, so a reply can differ from the atlas for the same neuron and α.
- Persona names are suggestions from the reply text. Nobody has checked them by hand.
- The teacher (on either model) can be wrong. When in doubt, the formula and the numbers
  in this primer are the reference.
