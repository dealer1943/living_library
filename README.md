# neuron-steer

A local lab for pushing **one or many** MLP neurons in Qwen3-8B and asking it
"Who are you?" (or anything else). It reproduces the single-neuron method of the
[Neuron Persona Library](https://qwen-neurons-site.vercel.app/) and lets you stack
several neurons at once.

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
cd neuron
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
