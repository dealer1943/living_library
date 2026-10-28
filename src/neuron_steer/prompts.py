"""Chat-template helpers for Qwen3 (thinking off by default) and thought/reply splitting."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_PROMPT = "Who are you?"

Message = dict[str, str]


def user_messages(prompt: str, system: str | None = None) -> list[Message]:
    msgs: list[Message] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return msgs


def render_chat(tokenizer: Any, messages: list[Message], enable_thinking: bool = False) -> str:
    """Render messages with the generation prompt appended.

    Qwen3 templates accept ``enable_thinking``; with it False the template inserts an
    empty <think></think> block so the model answers directly. Older/other templates
    reject the kwarg, so fall back without it.
    """
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=enable_thinking,
        )
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def split_thoughts(text: str) -> tuple[str, str]:
    """Split a decoded reply into ``(thoughts, reply)``.

    Handles a full ``<think>…</think>`` block, a bare ``…</think>`` (the opening tag was in
    the prompt), and an unclosed ``<think>…`` (all thought, no reply yet). Text outside the
    tags is the reply.
    """
    thoughts: list[str] = []
    rest = text
    if "</think>" in rest:
        head, rest = rest.split("</think>", 1)
        thoughts.append(head.replace("<think>", ""))
    while "<think>" in rest:
        before, after = rest.split("<think>", 1)
        if "</think>" in after:
            inner, after = after.split("</think>", 1)
        else:
            inner, after = after, ""
        thoughts.append(inner)
        rest = before + after
    return "\n\n".join(t.strip() for t in thoughts if t.strip()), rest.strip()


_REASONING_OPENERS = ("okay", "ok,", "alright", "all right", "hmm", "let me", "let's see", "wait",
                      "so the user", "so, the user", "the user", "first, i", "i need to", "i should",
                      "so the answer", "so, the answer", "so, to answer", "i think the answer",
                      "given the limited", "putting it all together")


def _is_reasoning(par: str) -> bool:
    p = par.strip().lower()
    return p.startswith(_REASONING_OPENERS) or "the user" in p[:200]


def split_reasoning(text: str) -> tuple[str, str]:
    """Split *untagged* thinking ("Okay, let's see. The user is asking…") off a reply.

    Paragraphs that read as reasoning before the reply proper, and from the first such
    paragraph after it ("I need to make sure…", "So, the answer to the user's question…"),
    go to ``thoughts``; the rest is the reply. A reply that is reasoning all the way down is
    left as it is rather than emptied.
    """
    pars = [p for p in text.split("\n\n") if p.strip()]
    i = 0
    while i < len(pars) and _is_reasoning(pars[i]):
        i += 1
    if i == len(pars):
        return "", text.strip()
    j = i + 1
    while j < len(pars) and not _is_reasoning(pars[j]):
        j += 1
    reply, tail = _cut_at_reasoning("\n\n".join(p.strip() for p in pars[i:j]))
    thoughts = [p.strip() for p in pars[:i]] + ([tail] if tail else []) + [p.strip() for p in pars[j:]]
    return "\n\n".join(thoughts), reply


_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_MID_REASONING = re.compile(r"\bthe user\b|\blet me (think|check|recall)\b|^(wait|hmm|okay)\b|"
                            r"\bthe answer (should|would|is that)\b|\bi need to\b", re.I)


def _cut_at_reasoning(reply: str) -> tuple[str, str]:
    """Within the reply, move everything from the first sentence that reasons *about* the
    question ("…and the user is asking…", "Let me think again.") into the thoughts; the
    first sentence always stays."""
    pos = [m.end() for m in _SENTENCE.finditer(reply)]
    starts = [0] + pos
    for k, st in enumerate(starts[1:], 1):
        end = starts[k + 1] if k + 1 < len(starts) else len(reply)
        if _MID_REASONING.search(reply[st:end]):
            return reply[:st].rstrip(), reply[st:].strip()
    return reply, ""


def strip_think(text: str) -> str:
    """Drop any (empty) <think>...</think> block from a decoded reply."""
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()
