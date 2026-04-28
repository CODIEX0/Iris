"""Text-to-speech node with Piper, pyttsx3, and console fallbacks."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import List

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from iris_msgs.msg import Viseme
from iris_msgs.srv import SpeakText


class TTSNode(Node):
    def __init__(self) -> None:
        super().__init__("tts_node")
        self.declare_parameter("backend", "auto")
        self.declare_parameter("piper_executable", "piper")
        self.declare_parameter("piper_voice", "")
        self.declare_parameter("speaking_rate_wpm", 145.0)
        self.declare_parameter("audio_player", "auto")

        self._backend = self._choose_backend(str(self.get_parameter("backend").value))
        self._lock = threading.Lock()
        self._viseme_pub = self.create_publisher(Viseme, "/mouth/viseme", 10)
        self.create_subscription(String, "/brain/response", self._on_response, 10)
        self.create_service(SpeakText, "/speech/say", self._on_say)
        self.get_logger().info(f"tts_node up backend={self._backend}")

    def _choose_backend(self, requested: str) -> str:
        requested = (requested or "auto").lower()
        if requested in {"piper", "pyttsx3", "console"}:
            if requested == "piper" and not self._piper_ready():
                self.get_logger().warn("Piper requested but executable/voice is missing; using console")
                return "console"
            if requested == "pyttsx3" and not self._pyttsx3_ready():
                self.get_logger().warn("pyttsx3 requested but unavailable; using console")
                return "console"
            return requested
        if self._piper_ready():
            return "piper"
        if self._pyttsx3_ready():
            return "pyttsx3"
        return "console"

    def _piper_ready(self) -> bool:
        executable = self._piper_executable()
        voice = Path(str(self.get_parameter("piper_voice").value)).expanduser()
        return Path(executable).exists() and voice.exists()

    def _piper_executable(self) -> str:
        configured = str(self.get_parameter("piper_executable").value).strip() or "piper"
        if "/" not in configured and "\\" not in configured:
            found = shutil.which(configured)
            if found:
                return found
        return str(Path(configured).expanduser())

    def _pyttsx3_ready(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
        except Exception:
            return False
        return True

    def _on_response(self, msg: String) -> None:
        threading.Thread(target=self._speak, args=(msg.data, "neutral"), daemon=True).start()

    def _on_say(self, req: SpeakText.Request, resp: SpeakText.Response):
        resp.duration = float(self._speak(req.text, req.emotion or "neutral"))
        resp.success = bool(req.text.strip())
        return resp

    def _speak(self, text: str, emotion: str) -> float:
        text = text.strip()
        if not text:
            return 0.0
        with self._lock:
            if self._backend == "piper":
                return self._speak_piper(text)
            if self._backend == "pyttsx3":
                return self._speak_pyttsx3(text)
            return self._speak_console(text, emotion)

    def _speak_piper(self, text: str) -> float:
        executable = self._piper_executable()
        voice = str(Path(str(self.get_parameter("piper_voice").value)).expanduser())
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            subprocess.run(
                [executable, "--model", voice, "--output_file", wav_path],
                input=text,
                text=True,
                check=True,
                timeout=30,
            )
            duration = self._wav_duration(wav_path) or self._estimate_duration(text)
            visemes = self._visemes_for_text(text, duration)
            thread = threading.Thread(target=self._publish_visemes, args=(visemes,), daemon=True)
            thread.start()
            self._play_wav(wav_path, duration)
            thread.join(timeout=0.2)
            self._publish_rest()
            return duration
        except Exception as exc:
            self.get_logger().error(f"Piper failed: {exc}; speaking to console")
            return self._speak_console(text, "neutral")
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def _speak_pyttsx3(self, text: str) -> float:
        import pyttsx3

        duration = self._estimate_duration(text)
        thread = threading.Thread(target=self._publish_visemes, args=(self._visemes_for_text(text, duration),), daemon=True)
        thread.start()
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        thread.join(timeout=0.2)
        self._publish_rest()
        return duration

    def _speak_console(self, text: str, emotion: str) -> float:
        duration = self._estimate_duration(text)
        thread = threading.Thread(target=self._publish_visemes, args=(self._visemes_for_text(text, duration),), daemon=True)
        thread.start()
        self.get_logger().info(f"say[{emotion}]: {text}")
        time.sleep(duration)
        thread.join(timeout=0.2)
        self._publish_rest()
        return duration

    def _play_wav(self, wav_path: str, duration: float) -> None:
        player = str(self.get_parameter("audio_player").value)
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

    def _wav_duration(self, wav_path: str) -> float:
        try:
            with wave.open(wav_path, "rb") as wav:
                return float(wav.getnframes()) / float(wav.getframerate())
        except Exception:
            return 0.0

    def _estimate_duration(self, text: str) -> float:
        words = max(1, len(text.split()))
        wpm = max(80.0, float(self.get_parameter("speaking_rate_wpm").value))
        return max(0.8, words / wpm * 60.0)

    def _visemes_for_text(self, text: str, duration: float) -> List[Viseme]:
        phonemes: List[str] = []
        for char in text.lower():
            if char in "bmp":
                phonemes.append("MM")
            elif char in "fv":
                phonemes.append("FF")
            elif char in "a":
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
        return [self._make_viseme(name, step, 1.0 if name != "rest" else 0.2) for name in phonemes]

    def _make_viseme(self, phoneme: str, duration: float, intensity: float) -> Viseme:
        msg = Viseme()
        msg.phoneme = phoneme
        msg.duration = float(duration)
        msg.intensity = float(intensity)
        return msg

    def _publish_visemes(self, visemes: List[Viseme]) -> None:
        for viseme in visemes:
            self._viseme_pub.publish(viseme)
            time.sleep(max(0.02, float(viseme.duration)))

    def _publish_rest(self) -> None:
        self._viseme_pub.publish(self._make_viseme("rest", 0.1, 0.0))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TTSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()