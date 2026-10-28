"""Chat-template helpers for Qwen3 (thinking off)."""

from __future__ import annotations

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


def strip_think(text: str) -> str:
    """Drop any (empty) <think>...</think> block from a decoded reply."""
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()
