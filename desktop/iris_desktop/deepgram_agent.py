from __future__ import annotations

import asyncio
import json
import time
from typing import Callable, Optional


TextCallback = Callable[[str, str], None]
VisemeCallback = Callable[[str, float, float], None]
PromptContextCallback = Callable[[str], Optional[str]]


class DeepgramAgent:
    def __init__(
        self,
        api_key: str,
        prompt: str,
        url: str = "wss://agent.deepgram.com/v1/agent/converse",
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
        listen_model: str = "nova-3",
        speak_model: str = "aura-2-thalia-en",
        think_provider: str = "open_ai",
        think_model: str = "gpt-4o-mini",
        echo_guard_seconds: float = 0.45,
        text_dedupe_seconds: float = 1.0,
        on_text: Optional[TextCallback] = None,
        on_viseme: Optional[VisemeCallback] = None,
        prompt_context: Optional[PromptContextCallback] = None,
    ) -> None:
        self.api_key = api_key
        self.prompt = prompt
        self.url = url
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.listen_model = listen_model
        self.speak_model = speak_model
        self.think_provider = think_provider
        self.think_model = think_model
        self.echo_guard_seconds = echo_guard_seconds
        self.text_dedupe_seconds = text_dedupe_seconds
        self.on_text = on_text
        self.on_viseme = on_viseme
        self.prompt_context = prompt_context
        self.error: Optional[BaseException] = None
        self._stop: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._audio_queue: Optional[asyncio.Queue[bytes]] = None
        self._input_stream = None
        self._output_stream = None
        self._viseme_index = 0
        self._input_muted_until = 0.0
        self._last_text_event: tuple[str, str, float] | None = None
        self._last_prompt_context = ""

    def stop_from_thread(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._audio_queue = asyncio.Queue()
        try:
            import sounddevice
            import websockets

            headers = {"Authorization": f"Token {self.api_key}"}
            websocket = await _connect(websockets, self.url, headers)
            async with websocket:
                await websocket.send(json.dumps(self._settings()))
                self._start_audio(sounddevice)
                await asyncio.gather(self._send_audio(websocket), self._receive(websocket))
        except BaseException as exc:
            self.error = exc
            raise
        finally:
            self._close_audio()

    def _settings(self) -> dict:
        return {
            "type": "Settings",
            "audio": {
                "input": {"encoding": "linear16", "sample_rate": self.input_sample_rate},
                "output": {"encoding": "linear16", "sample_rate": self.output_sample_rate, "container": "none"},
            },
            "agent": {
                "language": "en",
                "listen": {"provider": {"type": "deepgram", "model": self.listen_model}},
                "think": {
                    "provider": {"type": self.think_provider, "model": self.think_model},
                    "prompt": self.prompt,
                },
                "speak": {"provider": {"type": "deepgram", "model": self.speak_model}},
                "greeting": "Hi, I am Iris. I am ready to test voice mode.",
            },
        }

    def _start_audio(self, sounddevice) -> None:
        assert self._loop is not None
        assert self._audio_queue is not None

        def callback(indata, frames, timestamp, status) -> None:
            if time.monotonic() < self._input_muted_until:
                return
            if self._loop is not None and self._audio_queue is not None:
                self._loop.call_soon_threadsafe(self._audio_queue.put_nowait, bytes(indata))

        self._input_stream = sounddevice.RawInputStream(
            samplerate=self.input_sample_rate,
            blocksize=1024,
            dtype="int16",
            channels=1,
            callback=callback,
        )
        self._output_stream = sounddevice.RawOutputStream(
            samplerate=self.output_sample_rate,
            dtype="int16",
            channels=1,
        )
        self._input_stream.start()
        self._output_stream.start()

    def _close_audio(self) -> None:
        for stream in (self._input_stream, self._output_stream):
            if stream is not None:
                stream.stop()
                stream.close()

    async def _send_audio(self, websocket) -> None:
        assert self._audio_queue is not None
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                data = await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if time.monotonic() < self._input_muted_until:
                continue
            await websocket.send(data)

    async def _receive(self, websocket) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if isinstance(message, bytes):
                self._mute_input_for_output(message)
                if self._output_stream is not None:
                    self._output_stream.write(message)
                self._drop_pending_input()
                self._pulse_viseme()
                continue
            await self._handle_json(message, websocket)

    def _mute_input_for_output(self, audio: bytes) -> None:
        bytes_per_second = max(1, self.output_sample_rate * 2)
        audio_seconds = len(audio) / bytes_per_second
        muted_until = time.monotonic() + audio_seconds + self.echo_guard_seconds
        self._input_muted_until = max(self._input_muted_until, muted_until)

    def _drop_pending_input(self) -> None:
        if self._audio_queue is None:
            return
        while True:
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def _handle_json(self, raw: str, websocket) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        message_type = str(message.get("type", ""))
        role = str(message.get("role", "agent"))
        content = message.get("content") or message.get("text") or message.get("transcript")
        if content:
            text = str(content)
            self._emit_text(role, text)
            await self._send_prompt_context_if_needed(websocket, message_type, role, text)
        elif message_type and message_type in {"UserStartedSpeaking", "AgentThinking"}:
            self._emit_text("status", message_type)

    async def _send_prompt_context_if_needed(self, websocket, message_type: str, role: str, text: str) -> None:
        if self.prompt_context is None:
            return
        role_lower = role.lower()
        if role_lower in {"assistant", "agent"}:
            return
        if role_lower not in {"user", "human"} and message_type != "ConversationText":
            return
        try:
            prompt = self.prompt_context(text)
        except Exception as exc:
            self._emit_text("status", f"VisionContextError: {exc.__class__.__name__}")
            return
        if not prompt or prompt == self._last_prompt_context:
            return
        self._last_prompt_context = prompt
        await websocket.send(json.dumps({"type": "UpdatePrompt", "prompt": prompt}))

    def _emit_text(self, role: str, text: str) -> None:
        if self.on_text is None:
            return
        now = time.monotonic()
        if self._last_text_event is not None:
            last_role, last_text, last_at = self._last_text_event
            dedupe_seconds = 0.25 if role == "status" else self.text_dedupe_seconds
            if role == last_role and text == last_text and now - last_at <= dedupe_seconds:
                return
        self._last_text_event = (role, text, now)
        self.on_text(role, text)

    def _pulse_viseme(self) -> None:
        if self.on_viseme is None:
            return
        sequence = ["AA", "EE", "OH", "MM", "FF"]
        now_index = int(time.monotonic() * 12) % len(sequence)
        if now_index == self._viseme_index:
            return
        self._viseme_index = now_index
        self.on_viseme(sequence[now_index], 0.08, 0.8)


async def _connect(websockets, url: str, headers: dict):
    try:
        return await websockets.connect(url, extra_headers=headers)
    except TypeError:
        return await websockets.connect(url, additional_headers=headers)