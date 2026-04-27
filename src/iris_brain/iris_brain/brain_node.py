"""Brain node: consumes /speech/transcript, calls LLM, publishes reply + emotion."""
from __future__ import annotations

import collections
import threading
import time
from typing import Deque, Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from iris_msgs.msg import Emotion, Gesture
from iris_msgs.srv import SpeakText

from iris_brain.llm_backends import BackendError, build_backend
from iris_brain.personality import load_system_prompt, parse_emotion


class BrainNode(Node):
    def __init__(self) -> None:
        super().__init__("brain_node")
        self.declare_parameter("backend", "groq")
        self.declare_parameter("groq_model", "llama-3.1-8b-instant")
        self.declare_parameter("ollama_url", "http://localhost:11434")
        self.declare_parameter("ollama_model", "phi3:mini")
        self.declare_parameter("gemini_model", "gemini-1.5-flash")
        self.declare_parameter("max_tokens", 150)
        self.declare_parameter("temperature", 0.7)
        self.declare_parameter("personality_file", "kid_prompt.txt")
        self.declare_parameter("history_turns", 6)

        self.backend = self._init_backend()
        self.system_prompt = load_system_prompt(
            str(self.get_parameter("personality_file").value))
        self._history: Deque[Dict[str, str]] = collections.deque(
            maxlen=int(self.get_parameter("history_turns").value) * 2)
        self._gesture_hint: Optional[str] = None
        self._lock = threading.Lock()

        self.pub_reply = self.create_publisher(String, "/brain/response", 10)
        self.pub_emotion = self.create_publisher(Emotion, "/emotion/current", 10)
        self.create_subscription(String, "/speech/transcript", self._on_transcript, 10)
        self.create_subscription(Gesture, "/gesture/detected", self._on_gesture, 10)
        self.create_service(SpeakText, "/brain/ask", self._on_ask)

        self.get_logger().info(
            f"brain_node up backend={self.get_parameter('backend').value}"
        )

    def _init_backend(self):
        params = {
            "groq_model": self.get_parameter("groq_model").value,
            "ollama_url": self.get_parameter("ollama_url").value,
            "ollama_model": self.get_parameter("ollama_model").value,
            "gemini_model": self.get_parameter("gemini_model").value,
            "max_tokens": int(self.get_parameter("max_tokens").value),
            "temperature": float(self.get_parameter("temperature").value),
        }
        try:
            return build_backend(self.get_parameter("backend").value, **params)
        except BackendError as e:
            self.get_logger().error(f"backend init failed ({e}); falling back to ollama")
            return build_backend("ollama", **params)

    def _on_gesture(self, msg: Gesture) -> None:
        if msg.confidence > 0.7:
            self._gesture_hint = msg.name

    def _on_transcript(self, msg: String) -> None:
        threading.Thread(target=self._handle, args=(msg.data,), daemon=True).start()

    def _on_ask(self, req: SpeakText.Request, resp: SpeakText.Response):
        text, emotion = self._query(req.text)
        self._publish(text, emotion)
        resp.success = bool(text)
        resp.duration = 1.0
        return resp

    def _handle(self, text: str) -> None:
        if not text.strip():
            return
        reply, emotion = self._query(text)
        if not reply:
            return
        self._publish(reply, emotion)

    def _query(self, user_text: str):
        with self._lock:
            hint = self._gesture_hint
            self._gesture_hint = None
            messages: List[Dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self._history)
            context = user_text if not hint else f"{user_text}\n(the user is making a {hint} gesture)"
            messages.append({"role": "user", "content": context})
        start = time.monotonic()
        try:
            raw = self.backend.chat(messages)
        except Exception as e:
            self.get_logger().error(f"LLM call failed: {e}")
            return "Hmm, I'm having a little trouble thinking right now.", "thinking"
        cleaned, emotion = parse_emotion(raw)
        with self._lock:
            self._history.append({"role": "user", "content": user_text})
            self._history.append({"role": "assistant", "content": raw})
        self.get_logger().info(f"brain {time.monotonic()-start:.2f}s → {cleaned!r} [{emotion}]")
        return cleaned, emotion

    def _publish(self, text: str, emotion: str) -> None:
        self.pub_reply.publish(String(data=text))
        em = Emotion()
        em.emotion = emotion
        em.intensity = 1.0
        em.stamp = self.get_clock().now().to_msg()
        self.pub_emotion.publish(em)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BrainNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()