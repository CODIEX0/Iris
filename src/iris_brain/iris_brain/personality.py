"""Prompt loading + emotion tag parsing."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

from ament_index_python.packages import get_package_share_directory

EMOTION_TAG = re.compile(r"\[EMOTION:\s*(happy|sad|curious|thinking|excited|neutral)\s*\]",
                         re.IGNORECASE)
VALID = {"happy", "sad", "curious", "thinking", "excited", "neutral"}


def load_system_prompt(filename: str = "kid_prompt.txt") -> str:
    share = Path(get_package_share_directory("iris_brain")) / "resource" / filename
    if share.exists():
        return share.read_text()
    return (
        "You are Iris, a friendly humanoid robot for kids. Speak in one or "
        "two short sentences and end replies with [EMOTION: neutral]."
    )


def parse_emotion(reply: str) -> Tuple[str, str]:
    """Return (reply_without_tag, emotion). Defaults to 'neutral'."""
    m = EMOTION_TAG.search(reply)
    if not m:
        return reply.strip(), "neutral"
    emotion = m.group(1).lower()
    if emotion not in VALID:
        emotion = "neutral"
    cleaned = EMOTION_TAG.sub("", reply).strip()
    return cleaned, emotion