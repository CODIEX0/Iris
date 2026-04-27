"""Pluggable LLM backends: Groq (default), Ollama, Gemini."""
from __future__ import annotations

import os
from typing import Dict, List

import httpx


class BackendError(RuntimeError):
    pass


class GroqBackend:
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, model: str = "llama-3.1-8b-instant",
                 max_tokens: int = 150, temperature: float = 0.7,
                 timeout: float = 15.0) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.api_key = os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            raise BackendError("GROQ_API_KEY not set in environment")

    def chat(self, messages: List[Dict[str, str]]) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        r = httpx.post(self.URL, json=payload, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()


class OllamaBackend:
    def __init__(self, url: str = "http://localhost:11434",
                 model: str = "phi3:mini", max_tokens: int = 150,
                 temperature: float = 0.7, timeout: float = 60.0) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def chat(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        r = httpx.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "").strip()


class GeminiBackend:
    def __init__(self, model: str = "gemini-1.5-flash",
                 max_tokens: int = 150, temperature: float = 0.7,
                 timeout: float = 15.0) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        if not self.api_key:
            raise BackendError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")

    def chat(self, messages: List[Dict[str, str]]) -> str:
        system_parts: List[str] = []
        contents: List[Dict] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                system_parts.append(m["content"])
            else:
                contents.append({
                    "role": "user" if role == "user" else "model",
                    "parts": [{"text": m["content"]}],
                })
        if system_parts:
            contents.insert(0, {
                "role": "user",
                "parts": [{"text": "\n\n".join(system_parts)}],
            })
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }
        r = httpx.post(url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()


def build_backend(kind: str, **kwargs):
    kind = (kind or "groq").lower()
    if kind == "groq":
        return GroqBackend(
            model=kwargs.get("groq_model", "llama-3.1-8b-instant"),
            max_tokens=kwargs.get("max_tokens", 150),
            temperature=kwargs.get("temperature", 0.7),
        )
    if kind == "ollama":
        return OllamaBackend(
            url=kwargs.get("ollama_url", "http://localhost:11434"),
            model=kwargs.get("ollama_model", "phi3:mini"),
            max_tokens=kwargs.get("max_tokens", 150),
            temperature=kwargs.get("temperature", 0.7),
        )
    if kind == "gemini":
        return GeminiBackend(
            model=kwargs.get("gemini_model", "gemini-1.5-flash"),
            max_tokens=kwargs.get("max_tokens", 150),
            temperature=kwargs.get("temperature", 0.7),
        )
    raise BackendError(f"unknown backend: {kind}")