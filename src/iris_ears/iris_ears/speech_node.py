"""Speech-to-text node with Vosk microphone support and keyboard fallback."""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class SpeechNode(Node):
    def __init__(self) -> None:
        super().__init__("speech_node")
        self.declare_parameter("backend", "auto")
        self.declare_parameter("vosk_model_path", "")
        self.declare_parameter("sample_rate", 16000)
        self.declare_parameter("device", "")
        self.declare_parameter("publish_partials", False)

        self._pub = self.create_publisher(String, "/speech/transcript", 10)
        self._status_pub = self.create_publisher(String, "/speech/status", 10)
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self._stream = None
        self._recognizer = None
        self._keyboard_thread: Optional[threading.Thread] = None
        self._last_partial = ""

        backend = self._choose_backend(str(self.get_parameter("backend").value))
        if backend == "vosk":
            self._start_vosk()
        elif backend == "keyboard":
            self._start_keyboard()
        else:
            self.get_logger().warn("speech input disabled")
            self._publish_status("disabled")

    def _choose_backend(self, requested: str) -> str:
        requested = (requested or "auto").lower()
        if requested in {"keyboard", "disabled"}:
            return requested
        if requested == "vosk" or requested == "auto":
            if self._vosk_available():
                return "vosk"
            if requested == "vosk":
                self.get_logger().warn("Vosk requested but unavailable; falling back to keyboard")
        return "keyboard"

    def _vosk_available(self) -> bool:
        model_path = Path(str(self.get_parameter("vosk_model_path").value)).expanduser()
        if not model_path.exists():
            return False
        try:
            import sounddevice  # noqa: F401
            import vosk  # noqa: F401
        except Exception:
            return False
        return True

    def _start_vosk(self) -> None:
        import sounddevice
        import vosk

        sample_rate = int(self.get_parameter("sample_rate").value)
        model_path = str(Path(str(self.get_parameter("vosk_model_path").value)).expanduser())
        device = str(self.get_parameter("device").value) or None
        model = vosk.Model(model_path)
        self._recognizer = vosk.KaldiRecognizer(model, sample_rate)

        def callback(indata, frames, timestamp, status) -> None:
            if status:
                self.get_logger().warn(str(status))
            self._audio_queue.put(bytes(indata))

        self._stream = sounddevice.RawInputStream(
            samplerate=sample_rate,
            blocksize=8000,
            device=device,
            dtype="int16",
            channels=1,
            callback=callback,
        )
        self._stream.start()
        self.create_timer(0.05, self._poll_vosk)
        self._publish_status("listening")
        self.get_logger().info(f"speech_node up with Vosk model {model_path}")

    def _start_keyboard(self) -> None:
        self._keyboard_thread = threading.Thread(target=self._keyboard_loop, daemon=True)
        self._keyboard_thread.start()
        self._publish_status("keyboard")
        self.get_logger().info("speech_node up in keyboard mode; type phrases into the terminal")

    def _keyboard_loop(self) -> None:
        while rclpy.ok():
            try:
                text = input("iris> ").strip()
            except EOFError:
                time.sleep(0.5)
                continue
            except OSError:
                time.sleep(1.0)
                continue
            if text:
                self._publish_transcript(text)

    def _poll_vosk(self) -> None:
        if self._recognizer is None:
            return
        while not self._audio_queue.empty():
            data = self._audio_queue.get_nowait()
            if self._recognizer.AcceptWaveform(data):
                result = json.loads(self._recognizer.Result())
                self._publish_transcript(result.get("text", ""))
                self._last_partial = ""
            elif bool(self.get_parameter("publish_partials").value):
                partial = json.loads(self._recognizer.PartialResult()).get("partial", "")
                if partial and partial != self._last_partial:
                    self._last_partial = partial
                    self._publish_status(f"partial:{partial}")

    def _publish_transcript(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._pub.publish(String(data=text))
        self._publish_status("heard")
        self.get_logger().info(f"heard: {text}")

    def _publish_status(self, status: str) -> None:
        self._status_pub.publish(String(data=status))

    def destroy_node(self) -> bool:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SpeechNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()