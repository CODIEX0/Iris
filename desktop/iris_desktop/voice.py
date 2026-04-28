from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable, List, Optional, Tuple


VisemeCallback = Callable[[str, float, float], None]
StatusCallback = Callable[[str], None]


def visemes_for_text(text: str, duration: float) -> List[Tuple[str, float, float]]:
    phonemes: List[str] = []
    for char in text.lower():
        if char in "bmp":
            phonemes.append("MM")
        elif char in "fv":
            phonemes.append("FF")
        elif char == "a":
            phonemes.append("AA")
        elif char in "ei":
            phonemes.append("EE")
        elif char in "ou":
            phonemes.append("OH")
        elif char.isspace() or char in ".,!?;:":
            phonemes.append("rest")
    if not phonemes:
        phonemes = ["rest"]
    step = max(0.05, duration / len(phonemes))
    return [(name, step, 1.0 if name != "rest" else 0.2) for name in phonemes]


def estimate_duration(text: str, wpm: float = 145.0) -> float:
    words = max(1, len(text.split()))
    return max(0.8, words / max(80.0, wpm) * 60.0)


class OfflineRecognizer:
    def __init__(
        self,
        model_path: Path,
        backend: str = "auto",
        sample_rate: int = 16000,
        device: str = "",
        publish_partials: bool = False,
        on_status: Optional[StatusCallback] = None,
    ) -> None:
        self.model_path = model_path.expanduser()
        self.requested_backend = backend
        self.sample_rate = sample_rate
        self.device = device or None
        self.publish_partials = publish_partials
        self.on_status = on_status
        self.backend = "keyboard"
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self._text_queue: "queue.Queue[str]" = queue.Queue()
        self._stream = None
        self._recognizer = None
        self._keyboard_thread: Optional[threading.Thread] = None

    def start(self) -> str:
        if self.requested_backend == "keyboard":
            self._start_keyboard()
            return self.backend
        if self.model_path.exists():
            try:
                import sounddevice
                import vosk

                model = vosk.Model(str(self.model_path))
                self._recognizer = vosk.KaldiRecognizer(model, self.sample_rate)

                def callback(indata, frames, timestamp, status) -> None:
                    self._audio_queue.put(bytes(indata))

                self._stream = sounddevice.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=8000,
                    device=self.device,
                    dtype="int16",
                    channels=1,
                    callback=callback,
                )
                self._stream.start()
                self.backend = "vosk"
                self._status("listening")
                return self.backend
            except Exception as exc:
                print(f"Vosk microphone mode unavailable: {exc}")
        self._start_keyboard()
        return self.backend

    def _start_keyboard(self) -> None:
        if self._keyboard_thread is None:
            self._keyboard_thread = threading.Thread(target=self._keyboard_loop, daemon=True)
            self._keyboard_thread.start()
        self.backend = "keyboard"
        self._status("listening")

    def _keyboard_loop(self) -> None:
        while True:
            try:
                text = input("iris> ").strip()
            except (EOFError, OSError):
                time.sleep(0.5)
                continue
            if text:
                self._text_queue.put(text)

    def poll(self) -> Optional[str]:
        while self._recognizer is not None and not self._audio_queue.empty():
            data = self._audio_queue.get_nowait()
            if self._recognizer.AcceptWaveform(data):
                result = json.loads(self._recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    self._status("heard")
                    return text
            else:
                partial = json.loads(self._recognizer.PartialResult()).get("partial", "").strip()
                if partial:
                    self._status("hearing")
        try:
            text = self._text_queue.get_nowait()
            self._status("heard")
            return text
        except queue.Empty:
            return None

    def _status(self, status: str) -> None:
        if self.on_status is not None:
            self.on_status(status)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


class SpeechOutput:
    def __init__(self, backend: str, piper_executable: Path, piper_voice: Path, audio_player: str = "auto") -> None:
        self.backend = backend
        self.piper_executable = piper_executable.expanduser()
        self.piper_voice = piper_voice.expanduser()
        self.audio_player = audio_player
        self._lock = threading.Lock()
        self.backend = self._choose_backend(backend)

    def _choose_backend(self, requested: str) -> str:
        requested = (requested or "auto").lower()
        if requested == "piper" and self._piper_ready():
            return "piper"
        if requested == "pyttsx3" and self._pyttsx3_ready():
            return "pyttsx3"
        if requested == "console":
            return "console"
        if self._piper_ready():
            return "piper"
        if self._pyttsx3_ready():
            return "pyttsx3"
        return "console"

    def _piper_ready(self) -> bool:
        executable = self._resolve_piper_executable()
        return executable is not None and self.piper_voice.exists()

    def _resolve_piper_executable(self) -> Optional[str]:
        configured = str(self.piper_executable)
        if configured and self.piper_executable.exists():
            return configured
        found = shutil.which("piper")
        return found

    def _pyttsx3_ready(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
        except Exception:
            return False
        return True

    def speak_async(
        self,
        text: str,
        emotion: str,
        on_viseme: Optional[VisemeCallback] = None,
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        def run() -> None:
            try:
                self.speak(text, emotion, on_viseme)
            finally:
                if on_done is not None:
                    on_done()

        threading.Thread(target=run, daemon=True).start()

    def speak(self, text: str, emotion: str = "neutral", on_viseme: Optional[VisemeCallback] = None) -> float:
        text = text.strip()
        if not text:
            return 0.0
        with self._lock:
            if self.backend == "piper":
                return self._speak_piper(text, on_viseme)
            if self.backend == "pyttsx3":
                return self._speak_pyttsx3(text, on_viseme)
            return self._speak_console(text, emotion, on_viseme)

    def _speak_piper(self, text: str, on_viseme: Optional[VisemeCallback]) -> float:
        executable = self._resolve_piper_executable()
        if executable is None:
            return self._speak_console(text, "neutral", on_viseme)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            subprocess.run(
                [executable, "--model", str(self.piper_voice), "--output_file", wav_path],
                input=text,
                text=True,
                check=True,
                timeout=30,
            )
            duration = _wav_duration(wav_path) or estimate_duration(text)
            thread = _start_viseme_thread(text, duration, on_viseme)
            _play_wav(wav_path, duration, self.audio_player)
            thread.join(timeout=0.2)
            _rest(on_viseme)
            return duration
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def _speak_pyttsx3(self, text: str, on_viseme: Optional[VisemeCallback]) -> float:
        import pyttsx3

        duration = estimate_duration(text)
        thread = _start_viseme_thread(text, duration, on_viseme)
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        thread.join(timeout=0.2)
        _rest(on_viseme)
        return duration

    def _speak_console(self, text: str, emotion: str, on_viseme: Optional[VisemeCallback]) -> float:
        duration = estimate_duration(text)
        thread = _start_viseme_thread(text, duration, on_viseme)
        print(f"Iris[{emotion}]: {text}")
        time.sleep(duration)
        thread.join(timeout=0.2)
        _rest(on_viseme)
        return duration


def _start_viseme_thread(text: str, duration: float, on_viseme: Optional[VisemeCallback]) -> threading.Thread:
    def run() -> None:
        for phoneme, step, intensity in visemes_for_text(text, duration):
            if on_viseme is not None:
                on_viseme(phoneme, step, intensity)
            time.sleep(step)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _rest(on_viseme: Optional[VisemeCallback]) -> None:
    if on_viseme is not None:
        on_viseme("rest", 0.1, 0.0)


def _wav_duration(wav_path: str) -> float:
    try:
        with wave.open(wav_path, "rb") as wav:
            return float(wav.getnframes()) / float(wav.getframerate())
    except Exception:
        return 0.0


def _play_wav(wav_path: str, duration: float, audio_player: str) -> None:
    player = audio_player
    if player == "auto":
        player = "aplay" if shutil.which("aplay") else ""
    if player:
        subprocess.run([player, wav_path], check=False, timeout=max(duration + 3.0, 5.0))
        return
    try:
        import winsound

        winsound.PlaySound(wav_path, winsound.SND_FILENAME)
        return
    except Exception:
        pass
    time.sleep(duration)