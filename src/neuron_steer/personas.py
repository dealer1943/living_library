"""Checked-out personas (F00003–F00005): chat transcripts for single / mix / group tabs and the
five check-in keywords.

A tab's conversation is a *transcript*: ``[{"speaker": "user" | <member name>, "content": …}]``.
For the speaking persona it becomes a chat: its own lines are ``assistant`` turns and everyone
else's (you and the other personas in a group) are folded into ``user`` turns, each line prefixed
with the speaker's name in a group so the persona knows who said what.
"""

from __future__ import annotations

import re
from collections import Counter

from .prompts import Message

USER = "user"
GROUP_SYSTEM = (
    "This is a group conversation between a person (User) and several voices: {names}. You are {me}. "
    "Reply as yourself, in the first person, in one to three sentences. Speak only for yourself; "
    "never write lines for User or the others."
)

STOP = set("""
a about above after again against all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers herself him himself
his how i if in into is it its itself just like me more most my myself no nor not now of off on once only or other our ours
ourselves out over own same she should so some such than that the their theirs them themselves then there these they this
those through to too under until up very was we were what when where which while who whom why will with would you your
yours yourself yourselves user ok okay yes yeah oh well really thing things one get got let us say said tell think know
want going im i'm it's dont don't can't that's there's you're i've i'll
""".split())


def persona_messages(transcript: list[dict], me: str, group: list[str] | None = None) -> list[Message]:
    """``transcript`` -> chat messages from ``me``'s point of view (group: names prefixed, system line)."""
    out: list[Message] = []
    if group:
        names = ", ".join(group)
        out.append({"role": "system", "content": GROUP_SYSTEM.format(names=names, me=me)})
    for t in transcript:
        speaker, text = str(t.get("speaker") or USER), str(t.get("content") or "").strip()
        if not text:
            continue
        if speaker == me:
            out.append({"role": "assistant", "content": text})
            continue
        line = f"{'User' if speaker == USER else speaker}: {text}" if group else text
        if out and out[-1]["role"] == "user":
            out[-1]["content"] += "\n\n" + line
        else:
            out.append({"role": "user", "content": line})
    if group and out and out[-1]["role"] == "user":
        out[-1]["content"] += f"\n\n({me}, it is your turn. Reply in your own voice.)"
    return out


def strip_speaker(text: str, me: str) -> str:
    """Drop a leading ``Me:`` the model sometimes writes in a group, and anything after it starts
    speaking for someone else (``\\nUser: …``)."""
    tag = r"\s*[*_]*\s*({name})\s*[*_]*\s*:\s*[*_]*\s*"
    t = re.sub("^" + tag.format(name=re.escape(me)), "", text, flags=re.I)
    m = re.search(r"\n" + tag.format(name=r"User|[A-Z][\w .'-]{0,30}"), t)
    t = t[:m.start()] if m and m.start() > 0 else t
    t = re.sub("^" + tag.format(name=r"User"), "", t, flags=re.I)  # a bare echo of the room
    return t.strip()


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in STOP and not w.endswith("'s")]


def normalize_keywords(text: str, k: int = 5) -> list[str]:
    """``"Gothic, Lonely  poet!"`` -> ``["gothic", "lonely", "poet"]`` (lowercase, de-duplicated, ≤ k)."""
    words = [re.sub(r"[^a-z0-9'-]", "", w.lower()).strip("'-") for w in re.split(r"[\s,;/|]+", text or "")]
    return list(dict.fromkeys(w for w in words if w))[:k]


def keywords_from_text(text: str, k: int = 5, exclude: list[str] | None = None) -> list[str]:
    """Most frequent content words — the fallback when the librarian's answer is short."""
    skip = set(exclude or [])
    return [w for w, _ in Counter(w for w in _words(text) if w not in skip).most_common(k)]


def keyword_request(name: str, transcript: list[dict], max_chars: int = 3000) -> list[Message]:
    """Ask the librarian for five keywords describing the persona from its chat."""
    lines = [f"{'User' if t.get('speaker') == USER else t.get('speaker')}: {str(t.get('content') or '').strip()}"
             for t in transcript if str(t.get("content") or "").strip()]
    chat = "\n".join(lines)[-max_chars:] or "(no conversation)"
    return [
        {"role": "system", "content": "You are the chief librarian, cataloguing a neuron persona that was just "
                                      "checked back in. You answer with keywords only."},
        {"role": "user", "content": f"Here is the conversation with the persona “{name}”:\n\n{chat}\n\n"
                                    "Describe this persona with exactly five lowercase keywords, separated by single "
                                    "spaces. Reply with the five words only, nothing else."},
    ]


def pick_keywords(answer: str, transcript_text: str, k: int = 5, exclude: list[str] | None = None) -> list[str]:
    """The librarian's answer -> k keywords, topped up from the transcript if she gave fewer.
    ``exclude``: words that describe nothing (the personas' own names)."""
    skip = set(STOP) | {w.lower() for w in (exclude or [])}
    first = next((ln for ln in answer.strip().splitlines() if ln.strip()), "")
    kws = [w for w in normalize_keywords(first, k=12) if w not in skip and len(w) > 1 and not w.isdigit()][:k]
    if len(kws) < k:
        kws += keywords_from_text(transcript_text, k=k - len(kws), exclude=[*kws, *skip])
    return kws[:k]


def trim_repeats(text: str) -> str:
    """Drop sentences the persona already said in this reply (steered voices loop: "I am a virus
    that… I am a virus that…"). Keeps the first occurrence and the original spacing."""
    parts = re.split(r"(?<=[.!?])(\s+)", text)
    seen, out = set(), []
    for i in range(0, len(parts), 2):
        sent, gap = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        key = re.sub(r"\W+", " ", sent.lower()).strip()
        if key and key in seen:
            continue
        seen.add(key)
        out.append(sent + gap)
    return "".join(out).strip()


def is_echo(reply: str, transcript: list[dict]) -> bool:
    """True when a group member only parroted a line already said (steered voices do)."""
    key = lambda x: re.sub(r"\W+", " ", x.lower()).strip()
    r = key(reply)
    return not r or any(r == key(str(t.get("content") or "")) for t in transcript)
