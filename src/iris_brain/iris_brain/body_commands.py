from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BodyCommand:
    name: str
    speed_scale: float
    confirmation: str
    emotion: str = "happy"


_COMMAND_PATTERNS = [
    (
        "thumbs_up",
        "Sure. I will give a thumbs up.",
        "excited",
        [
            re.compile(r"\bthumbs?\s+up\b"),
            re.compile(r"\bgive\s+(me\s+)?a\s+thumbs?\s+up\b"),
        ],
    ),
    (
        "wave",
        "Sure. I will wave.",
        "happy",
        [
            re.compile(r"\bwave\b"),
            re.compile(r"\bsay\s+hello\s+with\s+(your\s+)?hand\b"),
            re.compile(r"\bmove\s+your\s+hand\b"),
        ],
    ),
    (
        "nod",
        "Sure. I will nod my head.",
        "happy",
        [
            re.compile(r"\bnod\b"),
            re.compile(r"\bnod\s+your\s+head\b"),
            re.compile(r"\bsay\s+yes\s+with\s+your\s+head\b"),
            re.compile(r"\byes\s+gesture\b"),
        ],
    ),
    (
        "idle",
        "Okay. I will relax my body.",
        "neutral",
        [
            re.compile(r"\bgo\s+idle\b"),
            re.compile(r"\brest\s+position\b"),
            re.compile(r"\brelax\s+(your\s+)?body\b"),
            re.compile(r"\bstop\s+moving\b"),
            re.compile(r"\bbe\s+still\b"),
        ],
    ),
]


def detect_body_command(text: str) -> Optional[BodyCommand]:
    normalized = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not normalized:
        return None
    speed_scale = _speed_scale(normalized)
    for name, confirmation, emotion, patterns in _COMMAND_PATTERNS:
        if any(pattern.search(normalized) for pattern in patterns):
            return BodyCommand(name=name, speed_scale=speed_scale, confirmation=confirmation, emotion=emotion)
    return None


def _speed_scale(text: str) -> float:
    if re.search(r"\b(slow|slowly|gentle|gently|careful|carefully)\b", text):
        return 0.65
    if re.search(r"\b(fast|quick|quickly|excited|big)\b", text):
        return 1.35
    return 1.0
