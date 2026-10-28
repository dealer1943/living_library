# library/

The chief librarian's catalogue lives here as `library.db` (SQLite, gitignored).
Schema and helpers: `src/neuron_steer/library.py`. Override the path with
`--library PATH` or `$NEURON_LIBRARY`.

Tables: `entries` (one card per `(layer, neuron, direction, model)`: alpha, reply,
persona, tags, weirdness, notes, created/updated) and `history` (replies that a
re-probe replaced). Export with `uv run neuron-steer lib export > catalogue.json`.
