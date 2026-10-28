#!/usr/bin/env bash
# Try a few single-neuron personas from the site, then stack them.
# Run from the repo root after `uv sync` (or prefix with `uv run`).
set -euo pipefail
NS="uv run neuron-steer"

$NS baseline

# Singles (alpha 1.25, the site's starting strength)
$NS who -n 7:271:+1.25     # smallpox (up)
$NS who -n 12:545:-1.25    # ghost (down)
$NS who -n 9:166:+1.25     # coffee (up)
$NS who -n 7:6011:+1.25    # buddha (up)

# Two at once, comma syntax, negative = push down
$NS who -n 8,1058,1.25 -n 7,271,-1

# Everything in the JSON file, with the baseline printed alongside
$NS who --json examples/multi_neuron.json --compare

# Raw mode: fixed +20 on the activation, no residual-norm scaling
$NS who --raw -n 8:1058:20
