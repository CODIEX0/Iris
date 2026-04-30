from __future__ import annotations

import re
from typing import Dict, List

import httpx

from iris_desktop.types import Reply


EMOTION_TAG = re.compile(r"\[EMOTION:\s*(happy|sad|curious|thinking|excited|neutral)\s*\]", re.IGNORECASE)
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
MARKDOWN_BULLET = re.compile(r"(?m)^\s*[*+-]\s+")
WHITESPACE = re.compile(r"\s+")


SYSTEM_PROMPT = (
    "You are Iris, a friendly humanoid robot for kids. Speak in one or two "
    "short spoken sentences. You have OpenCV camera vision that can track faces, "
    "notice profile faces, upper bodies, full body shapes, eyes, smiles, hands, "
    "motion, lighting, and nearby object-sized regions when the camera is enabled. "
    "When the local MobileNet SSD model is installed, you can name common objects "
    "like person, bottle, chair, car, dog, cat, bicycle, bus, and TV. Do not claim "
    "to identify who someone is. End every reply with [EMOTION: neutral], choosing "
    "from happy, sad, curious, thinking, excited, neutral. Speak in plain text only. "
    "Do not use markdown formatting, bullets, or asterisks for emphasis."
)


def clean_spoken_text(text: str) -> str:
    cleaned = text or ""
    cleaned = MARKDOWN_LINK.sub(r"\1", cleaned)
    cleaned = MARKDOWN_BULLET.sub("", cleaned)
    cleaned = re.sub(r"(?<=\d)\s*\*\s*(?=\d)", " times ", cleaned)
    cleaned = cleaned.replace("**", "")
    cleaned = cleaned.replace("*", "")
    cleaned = re.sub(r"[_`~]+", "", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    return WHITESPACE.sub(" ", cleaned).strip()


def parse_emotion(text: str) -> Reply:
    match = EMOTION_TAG.search(text or "")
    if not match:
        return Reply(clean_spoken_text(text), "neutral")
    emotion = match.group(1).lower()
    cleaned = clean_spoken_text(EMOTION_TAG.sub("", text))
    return Reply(cleaned, emotion)


class OfflineBrain:
    def __init__(self, backend: str = "auto", ollama_url: str = "http://localhost:11434", model: str = "phi3:mini") -> None:
        self.backend = backend
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.history: List[Dict[str, str]] = []
        self.use_ollama = backend in {"auto", "ollama"} and self._ollama_ready()

    def _ollama_ready(self) -> bool:
        try:
            response = httpx.get(f"{self.ollama_url}/api/tags", timeout=1.5)
            return response.status_code < 500
        except Exception:
            return False

    def reply(self, user_text: str) -> Reply:
        user_text = user_text.strip()
        if not user_text:
            return Reply("", "neutral")
        if self.use_ollama:
            try:
                return self._ollama_reply(user_text)
            except Exception:
                self.use_ollama = False
        return self._simple_reply(user_text)

    def _ollama_reply(self, user_text: str) -> Reply:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history[-6:])
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 140},
        }
        response = httpx.post(f"{self.ollama_url}/api/chat", json=payload, timeout=45.0)
        response.raise_for_status()
        raw = response.json().get("message", {}).get("content", "")
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": raw})
        return parse_emotion(raw)

    def _simple_reply(self, user_text: str) -> Reply:
        lowered = user_text.lower()
        if any(word in lowered for word in ("hello", "hi", "hey")):
            return Reply("Hi, I am Iris. I can hear you and see the room from here.", "happy")
        if "your name" in lowered:
            return Reply("My name is Iris, and I am practicing being a helpful robot friend.", "happy")
        if any(word in lowered for word in ("wave", "dance", "move")):
            return Reply("I heard the movement command. In desktop mode I will show it on my face first.", "excited")
        if "science" in lowered or "robot" in lowered:
            return Reply("Robots mix code, sensors, motors, and a lot of testing. What part should we explore?", "curious")
        return Reply(f"I heard you say: {user_text}. I am offline, so I am using my local voice brain.", "thinking")