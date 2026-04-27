"""Lightweight behavior coordinator for Iris."""
from __future__ import annotations

import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from iris_msgs.msg import Emotion, FaceDetectionArray, TouchEvent
from iris_msgs.srv import PlayGesture, SpeakText


class OrchestratorNode(Node):
    def __init__(self) -> None:
        super().__init__("orchestrator_node")
        self.declare_parameter("idle_gesture", "idle")
        self.declare_parameter("greeting_gesture", "wave")
        self.declare_parameter("response_gesture", "nod")
        self.declare_parameter("greeting_cooldown_sec", 45.0)
        self.declare_parameter("idle_after_sec", 8.0)

        self._state = "idle"
        self._last_face_seen = 0.0
        self._last_greeting = 0.0
        self._last_activity = time.monotonic()
        self._emotion = "neutral"

        self._state_pub = self.create_publisher(String, "/orchestrator/state", 10)
        self._brain = self.create_client(SpeakText, "/brain/ask")
        self._motion = self.create_client(PlayGesture, "/motion/play_gesture")

        self.create_subscription(FaceDetectionArray, "/vision/faces", self._on_faces, 10)
        self.create_subscription(String, "/speech/transcript", self._on_transcript, 10)
        self.create_subscription(String, "/brain/response", self._on_response, 10)
        self.create_subscription(Emotion, "/emotion/current", self._on_emotion, 10)
        self.create_subscription(TouchEvent, "/touch/event", self._on_touch, 10)
        self.create_timer(1.0, self._tick)
        self._publish_state()
        self.get_logger().info("orchestrator_node up")

    def _on_faces(self, msg: FaceDetectionArray) -> None:
        if not msg.faces:
            return
        now = time.monotonic()
        self._last_face_seen = now
        self._last_activity = now
        if now - self._last_greeting > float(self.get_parameter("greeting_cooldown_sec").value):
            self._last_greeting = now
            self._set_state("greeting")
            self._play_gesture(str(self.get_parameter("greeting_gesture").value), 1.0)
            self._ask_brain("A visitor just arrived. Greet them warmly in one short sentence.", "happy")

    def _on_transcript(self, msg: String) -> None:
        if msg.data.strip():
            self._last_activity = time.monotonic()
            self._set_state("listening")

    def _on_response(self, msg: String) -> None:
        if not msg.data.strip():
            return
        self._last_activity = time.monotonic()
        self._set_state("speaking")
        if self._emotion in {"happy", "excited"}:
            self._play_gesture(str(self.get_parameter("response_gesture").value), 1.0)

    def _on_emotion(self, msg: Emotion) -> None:
        self._emotion = msg.emotion or "neutral"

    def _on_touch(self, msg: TouchEvent) -> None:
        self._last_activity = time.monotonic()
        self._set_state("engaging")
        if msg.zone == "mouth":
            self._ask_brain("Someone tapped my mouth. Say a playful hello in one short sentence.", "happy")
        elif msg.zone in {"left_eye", "right_eye"}:
            self._ask_brain("Someone tapped near my eye. Say what you are looking at in one short sentence.", "curious")
        elif msg.action == TouchEvent.ACTION_SWIPE:
            self._play_gesture("wave", 1.2)
        else:
            self._play_gesture("nod", 1.0)

    def _tick(self) -> None:
        idle_after = float(self.get_parameter("idle_after_sec").value)
        if self._state != "idle" and time.monotonic() - self._last_activity > idle_after:
            self._set_state("idle")
            self._play_gesture(str(self.get_parameter("idle_gesture").value), 0.7)

    def _ask_brain(self, text: str, emotion: str) -> None:
        if not self._brain.service_is_ready():
            self._brain.wait_for_service(timeout_sec=0.1)
        if not self._brain.service_is_ready():
            self.get_logger().warn("/brain/ask service unavailable")
            return
        request = SpeakText.Request()
        request.text = text
        request.emotion = emotion
        self._brain.call_async(request)

    def _play_gesture(self, name: str, speed_scale: float) -> None:
        if not name:
            return
        if not self._motion.service_is_ready():
            self._motion.wait_for_service(timeout_sec=0.1)
        if not self._motion.service_is_ready():
            self.get_logger().warn("/motion/play_gesture service unavailable")
            return
        request = PlayGesture.Request()
        request.name = name
        request.speed_scale = float(speed_scale)
        self._motion.call_async(request)

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self._publish_state()

    def _publish_state(self) -> None:
        self._state_pub.publish(String(data=self._state))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = OrchestratorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()