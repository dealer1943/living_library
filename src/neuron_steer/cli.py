"""neuron-steer CLI: who / ask / baseline / chat / librarian / lib / serve (web)."""

from __future__ import annotations

import argparse
import sys

from .prompts import DEFAULT_PROMPT, Message, user_messages
from .steer import DEFAULT_MODEL, GenerationResult, NeuronSteer, Steer, load_steers_json, parse_steer

STEER_HELP = """\
steer syntax:
  -n L:N[:ALPHA]  or  -n L,N[,ALPHA]     ALPHA signed float (+ up, - down) or up/down; default +1.25
  --json FILE                            [{"layer":7,"neuron":271,"alpha":1.25,"direction":"up"}, ...]
  --raw                                  ALPHA is a fixed activation add (e.g. 20), no r_L normalisation

examples:
  neuron-steer who --neuron 8:1058:+1.25 --neuron 7:271:+1.0
  neuron-steer who -n 8,1058,1.25 -n 7,271,-1
  neuron-steer who --json examples/multi_neuron.json --compare
  neuron-steer who --raw -n 8:1058:20
  neuron-steer who --json examples/multi_neuron.json --compare --backend mlx   # 4-bit, low memory
  neuron-steer ask "What do you dream about?" -n 9:166:up
  neuron-steer baseline
  neuron-steer chat -n 12:545:down
  neuron-steer librarian                     # chief librarian (L9:367:down) files personas; mlx by default
  neuron-steer lib find coffee bean          # catalogue lookups without loading a model
  neuron-steer serve                         # web chat with the librarian at http://localhost:8765/
"""


def _add_common(p: argparse.ArgumentParser, steering: bool = True) -> None:
    g = p.add_argument_group("model / decoding")
    g.add_argument("--model", default=None,
                   help=f"model id or path (default {DEFAULT_MODEL}; with --backend mlx: mlx-community/Qwen3-8B-4bit)")
    g.add_argument("--backend", choices=["auto", "hf", "mlx"], default="auto",
                   help="hf = transformers/torch; mlx = mlx-lm (quantized, Apple Silicon). "
                        "auto picks mlx when the model id looks like an MLX repo (default auto)")
    g.add_argument("--device", default="auto", help="auto | cuda | mps | cpu (default auto)")
    g.add_argument("--dtype", default=None, help="bfloat16 | float16 | float32 (default: bf16 if available)")
    g.add_argument("--max-new-tokens", type=int, default=160)
    g.add_argument("--temperature", type=float, default=0.0, help="0 = greedy (default)")
    g.add_argument("--top-p", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--system", default=None, help="optional system message")
    g.add_argument("--no-repeat-stop", action="store_true", help="don't stop early on exact repeats")
    if steering:
        s = p.add_argument_group("steering")
        s.add_argument("-n", "--neuron", action="append", default=[], metavar="L:N[:ALPHA]",
                       help="neuron to push; repeatable")
        s.add_argument("--json", action="append", default=[], metavar="FILE", help="JSON list of steers; repeatable")
        s.add_argument("--raw", action="store_true", help="alpha = fixed activation add, no r_L normalisation")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="neuron-steer",
        description="Push Qwen3 MLP neurons (one or many) and ask who it is.",
        epilog=STEER_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    who = sub.add_parser("who", help='steered "Who are you?" (or --prompt)', epilog=STEER_HELP,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    who.add_argument("--prompt", default=DEFAULT_PROMPT)
    who.add_argument("--compare", action="store_true", help="also print the unsteered baseline")
    _add_common(who)

    ask = sub.add_parser("ask", help="steered arbitrary prompt", epilog=STEER_HELP,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    ask.add_argument("prompt")
    ask.add_argument("--compare", action="store_true", help="also print the unsteered baseline")
    _add_common(ask)

    base = sub.add_parser("baseline", help="same prompt, no hooks")
    base.add_argument("--prompt", default=DEFAULT_PROMPT)
    _add_common(base, steering=False)

    chat = sub.add_parser("chat", help="interactive multi-turn chat with steers active", epilog=STEER_HELP,
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_common(chat)

    lb = sub.add_parser(
        "librarian", help="chief librarian (L9:367:down): probe neurons, file personas, look them up",
        description="Interactive catalogue of steered 'Who are you?' personas, curated by the Librarian of "
                    "Alexandria (layer 9, neuron 367 pushed down). Default backend: mlx 4-bit. "
                    "-n steers are stacked on her voice for chat; probes always run the probed neuron alone.",
        epilog=STEER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    lb.add_argument("--library", default=None, help="catalogue path (default library/library.db or $NEURON_LIBRARY)")
    lb.add_argument("--alpha", type=float, default=1.25, help="probe magnitude (default 1.25)")
    lb.add_argument("--librarian-alpha", type=float, default=0.75,
                    help="her own push down on L9 N367 (default 0.75: the clearest librarian on the 4-bit model)")
    lb.add_argument("--auto-file", action="store_true", help="file every probe under the suggested name, no prompt")
    lb.add_argument("--voice", action="store_true", help="she remarks (one generated line) after each filing")
    lb.add_argument("--no-context", action="store_true", help="don't give her a catalogue summary when chatting")
    _add_common(lb)
    lb.set_defaults(backend="mlx")

    for name in ("serve", "web"):
        sv = sub.add_parser(
            name, help="web chat with the chief librarian (L9:367:down) + catalogue API on localhost"
            + (" (alias of serve)" if name == "web" else ""),
            description="Serve a ChatGPT-style page for talking to the Librarian of Alexandria, plus "
                        "/api/chat, /api/probe, /api/inventory, /api/find. The model loads once at startup "
                        "(mlx 4-bit by default). -n steers are stacked on her voice.",
            epilog=STEER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
        sv.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
        sv.add_argument("--port", type=int, default=8765, help="port (default 8765)")
        sv.add_argument("--library", default=None, help="catalogue path (default library/library.db or $NEURON_LIBRARY)")
        sv.add_argument("--alpha", type=float, default=1.25, help="default probe magnitude for /api/probe (1.25)")
        sv.add_argument("--librarian-alpha", type=float, default=0.75,
                        help="her own push down on L9 N367 (default 0.75)")
        sv.add_argument("--no-context", action="store_true", help="don't give her a catalogue summary when chatting")
        sv.add_argument("--no-model", action="store_true",
                        help="don't load the model: catalogue endpoints only (chat returns 503)")
        sv.add_argument("--log-level", default="warning", help="uvicorn log level (default warning)")
        _add_common(sv)
        sv.set_defaults(backend="mlx", max_new_tokens=400)

    lo = sub.add_parser("lib", help="catalogue one-shots (no model): find / open / inventory / recent / personas / export")
    lo.add_argument("--library", default=None, help="catalogue path (default library/library.db or $NEURON_LIBRARY)")
    lo.add_argument("--model", default=None, help="restrict to one model id (default: all)")
    lsub = lo.add_subparsers(dest="action", required=True)
    f = lsub.add_parser("find", help="persona lookup")
    f.add_argument("query", nargs="+")
    o = lsub.add_parser("open", help="both directions for one neuron")
    o.add_argument("layer", type=int)
    o.add_argument("neuron", type=int)
    lsub.add_parser("inventory", help="tested vs untested counts + next suggestions")
    r = lsub.add_parser("recent", help="most recently filed cards")
    r.add_argument("-k", type=int, default=10)
    lsub.add_parser("personas", help="persona names with counts")
    lsub.add_parser("export", help="dump the catalogue as JSON")
    return ap


def collect_steers(args: argparse.Namespace) -> list[Steer]:
    steers = [parse_steer(s, raw=args.raw) for s in getattr(args, "neuron", [])]
    for path in getattr(args, "json", []):
        steers += load_steers_json(path, force_raw=args.raw)
    return steers


def print_steers(steers: list[Steer]) -> None:
    if not steers:
        print("active steers: none (baseline)")
        return
    print(f"active steers ({len(steers)}):")
    for s in steers:
        print(f"  {s}")


def print_result(label: str, res: GenerationResult) -> None:
    if res.applied:
        print("applied:")
        for a in res.applied:
            print(f"  {a}")
    note = " [stopped: exact repeat]" if res.stopped_on_repeat else ""
    print(f"\n--- {label} ({res.n_new_tokens} tokens){note} ---")
    print(res.text)
    print()


def _gen_kwargs(args: argparse.Namespace) -> dict:
    return dict(max_new_tokens=args.max_new_tokens, temperature=args.temperature,
                top_p=args.top_p, repeat_stop=not args.no_repeat_stop)


def _load(args: argparse.Namespace) -> NeuronSteer:
    backend = args.backend
    if backend == "auto":
        from .mlx_steer import is_mlx_model
        backend = "mlx" if args.model and is_mlx_model(args.model) else "hf"
    if backend == "mlx":
        from .mlx_steer import DEFAULT_MLX_MODEL, MLXNeuronSteer
        args.model = args.model or DEFAULT_MLX_MODEL
        if args.seed is not None:
            import mlx.core as mx
            mx.random.seed(args.seed)
        print(f"loading {args.model} (mlx) ...", file=sys.stderr)
        lab = MLXNeuronSteer(args.model)
    else:
        args.model = args.model or DEFAULT_MODEL
        if args.seed is not None:
            import torch
            torch.manual_seed(args.seed)
        print(f"loading {args.model} ...", file=sys.stderr)
        lab = NeuronSteer(args.model, device=args.device, dtype=args.dtype)
    print(f"device={lab.device} dtype={lab.dtype} layers={lab.n_layers} neurons/layer={lab.n_neurons}",
          file=sys.stderr)
    return lab


CHAT_HELP = """commands:
  /steers            list active steers
  /add L:N[:ALPHA]   add a steer (uses --raw setting)
  /rm L:N            remove steers on that layer/neuron
  /clear             remove all steers
  /off | /on         temporarily disable / re-enable steering
  /reset             forget conversation history
  /quit              exit"""


def run_chat(lab: NeuronSteer, args: argparse.Namespace, steers: list[Steer]) -> None:
    history: list[Message] = []
    if args.system:
        history.append({"role": "system", "content": args.system})
    enabled = True
    print_steers(steers)
    print(CHAT_HELP)
    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, rest = line.partition(" ")
            try:
                if cmd in ("/quit", "/exit", "/q"):
                    return
                elif cmd == "/steers":
                    print_steers(steers if enabled else [])
                elif cmd == "/add":
                    s = parse_steer(rest.strip(), raw=args.raw)
                    lab.validate([s])
                    steers.append(s)
                    print_steers(steers)
                elif cmd == "/rm":
                    L, N = (int(x) for x in rest.replace(",", ":").split(":")[:2])
                    steers[:] = [s for s in steers if (s.layer, s.neuron) != (L, N)]
                    print_steers(steers)
                elif cmd == "/clear":
                    steers.clear()
                    print_steers(steers)
                elif cmd == "/off":
                    enabled = False
                    print("steering OFF")
                elif cmd == "/on":
                    enabled = True
                    print_steers(steers)
                elif cmd == "/reset":
                    history = [m for m in history if m["role"] == "system"]
                    print("history cleared")
                else:
                    print(CHAT_HELP)
            except ValueError as e:
                print(f"error: {e}")
            continue

        history.append({"role": "user", "content": line})
        res = lab.generate(history, steers if enabled else [], **_gen_kwargs(args))
        history.append({"role": "assistant", "content": res.text})
        print(f"\nqwen> {res.text}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "lib":
        from .librarian import run_lib_oneshot
        return run_lib_oneshot(args)
    try:
        steers = collect_steers(args)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.cmd in ("serve", "web"):
        from .web import run_server
        args.extra_steers = steers
        return run_server(args)

    if args.cmd == "baseline" or (args.cmd in ("who", "ask") and not steers):
        if args.cmd != "baseline":
            print("note: no steers given; running baseline", file=sys.stderr)
        steers = []

    lab = _load(args)
    try:
        lab.validate(steers)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.cmd == "chat":
        run_chat(lab, args, steers)
        return 0
    if args.cmd == "librarian":
        from .librarian import run_librarian
        args.extra_steers = steers
        run_librarian(lab, args)
        return 0

    messages = user_messages(args.prompt, args.system)
    print(f"prompt: {args.prompt!r}")
    print_steers(steers)
    if getattr(args, "compare", False) and steers:
        print_result("baseline", lab.generate(messages, [], **_gen_kwargs(args)))
    label = "steered" if steers else "baseline"
    print_result(label, lab.generate(messages, steers, **_gen_kwargs(args)))
    if args.backend == "mlx" or "mlx" in str(getattr(lab, "device", "")):
        try:
            import mlx.core as mx
            print(f"mlx peak memory: {mx.get_peak_memory() / 2**30:.2f} GiB", file=sys.stderr)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
