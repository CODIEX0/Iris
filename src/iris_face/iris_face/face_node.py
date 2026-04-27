"""Pygame touchscreen face for Iris."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import rclpy
from rclpy.node import Node

from iris_msgs.msg import Emotion, FaceDetectionArray, TouchEvent, Viseme


@dataclass
class EyeTarget:
    x: float = 0.5
    y: float = 0.4


class FaceNode(Node):
    def __init__(self) -> None:
        super().__init__("face_node")
        self.declare_parameter("width", 800)
        self.declare_parameter("height", 480)
        self.declare_parameter("fullscreen", False)
        self.declare_parameter("headless", False)
        self.declare_parameter("rate_hz", 30.0)

        self.width = int(self.get_parameter("width").value)
        self.height = int(self.get_parameter("height").value)
        self.emotion = "neutral"
        self.intensity = 0.8
        self.viseme = "rest"
        self.eye_target = EyeTarget()
        self._mouse_down: Optional[Tuple[int, int, float]] = None
        self._pygame = None
        self._screen = None
        self._clock = None

        self._touch_pub = self.create_publisher(TouchEvent, "/touch/event", 10)
        self.create_subscription(Emotion, "/emotion/current", self._on_emotion, 10)
        self.create_subscription(Viseme, "/mouth/viseme", self._on_viseme, 10)
        self.create_subscription(FaceDetectionArray, "/vision/faces", self._on_faces, 10)

        self._init_pygame()
        rate_hz = float(self.get_parameter("rate_hz").value)
        self.create_timer(1.0 / rate_hz, self._tick)
        self.get_logger().info(f"face_node up {self.width}x{self.height} headless={self._screen is None}")

    def _init_pygame(self) -> None:
        if bool(self.get_parameter("headless").value):
            return
        try:
            import pygame
        except Exception:
            self.get_logger().warn("pygame unavailable; face running headless")
            return
        self._pygame = pygame
        pygame.init()
        flags = pygame.FULLSCREEN if bool(self.get_parameter("fullscreen").value) else 0
        self._screen = pygame.display.set_mode((self.width, self.height), flags)
        pygame.display.set_caption("Iris")
        self._clock = pygame.time.Clock()

    def _on_emotion(self, msg: Emotion) -> None:
        self.emotion = msg.emotion or "neutral"
        self.intensity = max(0.0, min(1.0, float(msg.intensity or 0.8)))

    def _on_viseme(self, msg: Viseme) -> None:
        self.viseme = msg.phoneme or "rest"

    def _on_faces(self, msg: FaceDetectionArray) -> None:
        if not msg.faces:
            self.eye_target = EyeTarget()
            return
        face = max(msg.faces, key=lambda item: item.confidence)
        self.eye_target = EyeTarget(face.gaze_target.x, face.gaze_target.y)

    def _tick(self) -> None:
        if self._pygame is None or self._screen is None:
            return
        self._handle_events()
        self._draw()
        self._pygame.display.flip()
        if self._clock is not None:
            self._clock.tick(float(self.get_parameter("rate_hz").value))

    def _handle_events(self) -> None:
        pygame = self._pygame
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                rclpy.shutdown()
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._mouse_down = (event.pos[0], event.pos[1], time.monotonic())
            elif event.type == pygame.MOUSEBUTTONUP and self._mouse_down is not None:
                start_x, start_y, start_t = self._mouse_down
                end_x, end_y = event.pos
                self._mouse_down = None
                self._publish_touch(start_x, start_y, end_x, end_y, time.monotonic() - start_t)

    def _publish_touch(self, start_x: int, start_y: int, end_x: int, end_y: int, held: float) -> None:
        msg = TouchEvent()
        msg.zone = self._zone_for_point(start_x, start_y)
        distance = math.hypot(end_x - start_x, end_y - start_y)
        if distance > 50:
            msg.action = TouchEvent.ACTION_SWIPE
        elif held > 0.7:
            msg.action = TouchEvent.ACTION_LONG_PRESS
        else:
            msg.action = TouchEvent.ACTION_TAP
        self._touch_pub.publish(msg)

    def _zone_for_point(self, x: int, y: int) -> str:
        nx = x / max(1, self.width)
        ny = y / max(1, self.height)
        if 0.24 <= nx <= 0.38 and 0.32 <= ny <= 0.52:
            return "left_eye"
        if 0.62 <= nx <= 0.76 and 0.32 <= ny <= 0.52:
            return "right_eye"
        if 0.44 <= nx <= 0.56 and 0.45 <= ny <= 0.62:
            return "nose"
        if 0.35 <= nx <= 0.65 and 0.64 <= ny <= 0.82:
            return "mouth"
        return "cheek"

    def _draw(self) -> None:
        pygame = self._pygame
        screen = self._screen
        screen.fill((26, 28, 32))
        center_x = self.width // 2
        face_rect = pygame.Rect(160, 34, self.width - 320, self.height - 52)
        hair_rect = pygame.Rect(132, 14, self.width - 264, self.height - 18)
        pygame.draw.ellipse(screen, (58, 39, 52), hair_rect)
        pygame.draw.ellipse(screen, (242, 190, 164), face_rect)
        pygame.draw.arc(screen, (88, 52, 68), hair_rect, math.pi, math.tau, 28)
        self._draw_cheeks(screen, pygame)
        self._draw_eyes(screen, pygame)
        self._draw_mouth(screen, pygame, center_x)

    def _draw_cheeks(self, screen, pygame) -> None:
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 2.0)
        color = (230, 126 + int(20 * pulse), 140)
        pygame.draw.ellipse(screen, color, pygame.Rect(210, 268, 72, 34))
        pygame.draw.ellipse(screen, color, pygame.Rect(self.width - 282, 268, 72, 34))

    def _draw_eyes(self, screen, pygame) -> None:
        blink = abs(math.sin(time.monotonic() * 0.55)) > 0.985
        offset_x = int((self.eye_target.x - 0.5) * 24)
        offset_y = int((self.eye_target.y - 0.4) * 18)
        for cx in (290, self.width - 290):
            rect = pygame.Rect(cx - 52, 170, 104, 62)
            pygame.draw.ellipse(screen, (250, 247, 238), rect)
            if blink:
                pygame.draw.rect(screen, (242, 190, 164), rect)
                pygame.draw.line(screen, (55, 42, 48), (cx - 45, 201), (cx + 45, 201), 5)
            else:
                pygame.draw.circle(screen, (63, 105, 116), (cx + offset_x, 201 + offset_y), 22)
                pygame.draw.circle(screen, (22, 30, 36), (cx + offset_x, 201 + offset_y), 11)
                pygame.draw.circle(screen, (255, 255, 255), (cx + offset_x + 7, 194 + offset_y), 5)

    def _draw_mouth(self, screen, pygame, center_x: int) -> None:
        y = 338
        if self.viseme == "MM":
            pygame.draw.line(screen, (90, 38, 48), (center_x - 58, y), (center_x + 58, y), 8)
            return
        if self.viseme == "FF":
            pygame.draw.ellipse(screen, (92, 36, 47), pygame.Rect(center_x - 58, y - 12, 116, 28))
            pygame.draw.rect(screen, (248, 244, 230), pygame.Rect(center_x - 48, y - 12, 96, 9))
            return
        if self.viseme == "OH":
            pygame.draw.ellipse(screen, (84, 31, 44), pygame.Rect(center_x - 34, y - 34, 68, 74))
            return
        if self.viseme == "AA":
            pygame.draw.ellipse(screen, (84, 31, 44), pygame.Rect(center_x - 54, y - 28, 108, 64))
            return
        if self.viseme == "EE":
            pygame.draw.ellipse(screen, (84, 31, 44), pygame.Rect(center_x - 70, y - 12, 140, 34))
            pygame.draw.rect(screen, (248, 244, 230), pygame.Rect(center_x - 50, y - 9, 100, 9))
            return
        if self.emotion in {"happy", "excited", "curious"}:
            pygame.draw.arc(screen, (84, 31, 44), pygame.Rect(center_x - 82, y - 48, 164, 86), 0.15, math.pi - 0.15, 8)
        elif self.emotion == "sad":
            pygame.draw.arc(screen, (84, 31, 44), pygame.Rect(center_x - 70, y - 2, 140, 78), math.pi + 0.2, math.tau - 0.2, 8)
        else:
            pygame.draw.line(screen, (84, 31, 44), (center_x - 54, y), (center_x + 54, y), 7)

    def destroy_node(self) -> bool:
        if self._pygame is not None:
            self._pygame.quit()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = FaceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()