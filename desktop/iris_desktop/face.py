from __future__ import annotations

import math
import threading
import time
from typing import Callable, Optional, Tuple

from iris_desktop.types import EyeTarget, Touch


class FaceWindow:
    def __init__(self, width: int = 800, height: int = 480, fullscreen: bool = False) -> None:
        import pygame

        self.width = width
        self.height = height
        self.emotion = "neutral"
        self.viseme = "rest"
        self.state = "listening"
        self.eye_target = EyeTarget()
        self.on_touch: Optional[Callable[[Touch], None]] = None
        self._lock = threading.Lock()
        self._mouse_down: Optional[Tuple[int, int, float]] = None
        self._pygame = pygame
        pygame.init()
        flags = pygame.FULLSCREEN if fullscreen else 0
        self._screen = pygame.display.set_mode((width, height), flags)
        pygame.display.set_caption("Iris Desktop")
        self._clock = pygame.time.Clock()
        self._last_viseme_at = 0.0

    def set_emotion(self, emotion: str) -> None:
        with self._lock:
            self.emotion = emotion or "neutral"

    def set_state(self, state: str) -> None:
        with self._lock:
            self.state = state or "listening"

    def set_viseme(self, phoneme: str, duration: float = 0.1, intensity: float = 1.0) -> None:
        with self._lock:
            self.viseme = phoneme or "rest"
            if self.viseme != "rest":
                self.state = "speaking"
                self._last_viseme_at = time.monotonic()
            elif self.state == "speaking":
                self.state = "listening"

    def set_eye_target(self, target: EyeTarget) -> None:
        with self._lock:
            self.eye_target = target

    def step(self) -> bool:
        self._handle_events()
        self._draw()
        self._pygame.display.flip()
        self._clock.tick(30)
        return True

    def close(self) -> None:
        self._pygame.quit()

    def _handle_events(self) -> None:
        pygame = self._pygame
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise KeyboardInterrupt
            if event.type == pygame.MOUSEBUTTONDOWN:
                self._mouse_down = (event.pos[0], event.pos[1], time.monotonic())
            elif event.type == pygame.MOUSEBUTTONUP and self._mouse_down is not None:
                start_x, start_y, start_t = self._mouse_down
                self._mouse_down = None
                touch = self._touch_for(start_x, start_y, event.pos[0], event.pos[1], time.monotonic() - start_t)
                if self.on_touch is not None:
                    self.on_touch(touch)

    def _touch_for(self, start_x: int, start_y: int, end_x: int, end_y: int, held: float) -> Touch:
        distance = math.hypot(end_x - start_x, end_y - start_y)
        if distance > 50:
            action = "swipe"
        elif held > 0.7:
            action = "long_press"
        else:
            action = "tap"
        return Touch(self._zone_for(start_x, start_y), action)

    def _zone_for(self, x: int, y: int) -> str:
        nx = x / max(1, self.width)
        ny = y / max(1, self.height)
        if 0.24 <= nx <= 0.38 and 0.32 <= ny <= 0.52:
            return "left_eye"
        if 0.62 <= nx <= 0.76 and 0.32 <= ny <= 0.52:
            return "right_eye"
        if 0.35 <= nx <= 0.65 and ny >= 0.58:
            return "mouth"
        return "screen"

    def _draw(self) -> None:
        pygame = self._pygame
        screen = self._screen
        with self._lock:
            emotion = self.emotion
            viseme = self.viseme
            target = self.eye_target
            state = self.state
            last_viseme_at = self._last_viseme_at
        if state == "speaking" and viseme == "rest" and time.monotonic() - last_viseme_at > 0.35:
            state = "listening"
        now = time.monotonic()
        mood = self._visual_mood(emotion, state)
        screen.fill((11, 14, 20))
        center_x = self.width // 2
        head = self._head_rect(pygame)
        self._draw_interface_background(screen, pygame, now, state)
        self._draw_eyes(screen, pygame, head, target, mood, state, now)
        self._draw_mouth(screen, pygame, head, center_x, mood, viseme, state, now)

    def _scale(self, value: float) -> int:
        return int(value * min(self.width / 800.0, self.height / 480.0))

    def _head_rect(self, pygame):
        head_w = min(int(self.width * 0.56), self._scale(430))
        head_h = min(int(self.height * 0.90), self._scale(430))
        head_w = max(head_w, self._scale(300))
        head_h = max(head_h, self._scale(330))
        rect = pygame.Rect(0, 0, head_w, head_h)
        rect.center = (self.width // 2, int(self.height * 0.53))
        return rect

    def _mix(self, a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
        amount = max(0.0, min(1.0, amount))
        return tuple(int(a[i] + (b[i] - a[i]) * amount) for i in range(3))

    def _visual_mood(self, emotion: str, state: str) -> str:
        if state in {"listening", "thinking"}:
            return state
        if emotion in {"happy", "sad", "curious", "thinking", "excited"}:
            return emotion
        return "neutral"

    def _draw_interface_background(self, screen, pygame, now: float, state: str) -> None:
        for i in range(12):
            y = int(self.height * i / 12)
            color = self._mix((3, 5, 10), (12, 14, 21), i / 13)
            pygame.draw.rect(screen, color, pygame.Rect(0, y, self.width, max(1, self.height // 12 + 1)))

    def _draw_neck(self, screen, pygame, center_x: int, head) -> None:
        shadow = pygame.Rect(center_x - self._scale(145), head.bottom - self._scale(12), self._scale(290), self._scale(44))
        pygame.draw.ellipse(screen, (12, 13, 18), shadow)

    def _draw_side_sensors(self, screen, pygame, head, now: float, state: str) -> None:
        return

    def _draw_head_shell(self, screen, pygame, head, now: float, mood: str) -> None:
        shadow = head.inflate(self._scale(34), self._scale(20))
        shadow.move_ip(0, self._scale(12))
        pygame.draw.ellipse(screen, (8, 9, 13), shadow)
        glow_color = (255, 139, 183) if mood == "listening" else (120, 185, 196)
        pygame.draw.ellipse(screen, self._mix((34, 31, 43), glow_color, 0.24), head.inflate(self._scale(18), self._scale(14)))
        for step in range(7):
            t = step / 6
            rect = head.inflate(-self._scale(step * 9), -self._scale(step * 8))
            color = self._mix((213, 225, 225), (252, 249, 239), t)
            pygame.draw.ellipse(screen, color, rect)
        pygame.draw.arc(screen, (255, 255, 248), head.inflate(-self._scale(42), -self._scale(36)), math.pi * 1.09, math.pi * 1.66, max(1, self._scale(5)))

    def _draw_face_plate(self, screen, pygame, head, mood: str) -> None:
        face = head.inflate(-self._scale(58), -self._scale(50))
        face.top += self._scale(24)
        pygame.draw.ellipse(screen, (244, 238, 229), face)
        pygame.draw.ellipse(screen, (255, 253, 246), face.inflate(-self._scale(24), -self._scale(28)))
        blush_base = (255, 213, 221) if mood != "sad" else (196, 218, 235)
        for side in (-1, 1):
            cheek = pygame.Rect(head.centerx + side * self._scale(70) - self._scale(58), head.top + self._scale(250), self._scale(116), self._scale(58))
            pygame.draw.ellipse(screen, blush_base, cheek)

    def _draw_forehead(self, screen, pygame, head, now: float, state: str, mood: str) -> None:
        color = (255, 140, 184) if state == "listening" else (142, 204, 213)
        pulse = 0.5 + 0.5 * math.sin(now * 4.0)
        center = (head.centerx, head.top + self._scale(74))
        pygame.draw.circle(screen, self._mix((242, 236, 230), color, 0.55 if state == "listening" else 0.25), center, self._scale(9 + pulse * 3))
        pygame.draw.circle(screen, (255, 255, 250), center, self._scale(4))

    def _draw_brows(self, screen, pygame, head, mood: str, state: str, now: float) -> None:
        eye_y = head.top + self._scale(176)
        left_x = head.centerx - self._scale(96)
        right_x = head.centerx + self._scale(96)
        lift = self._scale(0)
        inner_drop = self._scale(0)
        if mood == "happy":
            lift = self._scale(8)
        elif mood == "sad":
            inner_drop = self._scale(-12)
        elif mood == "curious":
            lift = self._scale(12)
        elif mood == "thinking":
            inner_drop = self._scale(8)
        elif mood == "excited":
            lift = self._scale(15)
        shimmer = int(math.sin(now * 2.0) * self._scale(2)) if state == "listening" else 0
        self._draw_brow(screen, pygame, left_x, eye_y - lift + shimmer, -1, inner_drop, mood)
        self._draw_brow(screen, pygame, right_x, eye_y - (lift if mood != "curious" else self._scale(2)) - shimmer, 1, inner_drop, mood)

    def _draw_brow(self, screen, pygame, cx: int, y: int, side: int, inner_drop: int, mood: str) -> None:
        outer = (cx - side * self._scale(45), y + self._scale(5))
        middle = (cx, y - self._scale(4))
        inner = (cx + side * self._scale(45), y + inner_drop)
        color = (91, 82, 96) if mood != "sad" else (87, 103, 124)
        pygame.draw.arc(screen, color, pygame.Rect(cx - self._scale(48), y - self._scale(22), self._scale(96), self._scale(42)), 0.15 if side < 0 else 0.1, math.pi - 0.15 if side < 0 else math.pi - 0.1, max(2, self._scale(4)))
        pygame.draw.line(screen, self._mix(color, (255, 255, 250), 0.35), outer, middle, max(1, self._scale(2)))
        pygame.draw.line(screen, self._mix(color, (255, 255, 250), 0.35), middle, inner, max(1, self._scale(2)))

    def _draw_eyes(self, screen, pygame, head, target: EyeTarget, mood: str, state: str, now: float) -> None:
        blink = abs(math.sin(now * 0.55)) > 0.985 and state != "listening"
        pulse = 0.5 + 0.5 * math.sin(now * 5.0)
        offset_x = int((target.x - 0.5) * self.width * 0.045)
        offset_y = int((target.y - 0.4) * self.height * 0.055)
        if mood == "thinking":
            offset_x += int(math.sin(now * 2.8) * self._scale(8))
            offset_y -= self._scale(4)
        eye_y = head.top + self._scale(204)
        eye_w = self._scale(126)
        eye_h = self._scale(78)
        if mood == "excited":
            eye_h = self._scale(84)
        elif mood == "happy":
            eye_h = self._scale(66)
        elif mood == "sad":
            eye_h = self._scale(62)
            offset_y += self._scale(4)
        pupil_radius = max(9, self._scale(18))
        centers = (head.centerx - self._scale(88), head.centerx + self._scale(88))
        iris_color = (83, 137, 151)
        for cx in centers:
            rect = pygame.Rect(cx - eye_w // 2, eye_y - eye_h // 2, eye_w, eye_h)
            pygame.draw.ellipse(screen, (255, 255, 250), rect)
            pygame.draw.ellipse(screen, (222, 234, 233), rect.inflate(-self._scale(16), -self._scale(14)), max(1, self._scale(2)))
            if blink:
                pygame.draw.ellipse(screen, (255, 253, 246), rect)
                pygame.draw.arc(screen, (98, 88, 102), rect.inflate(-self._scale(4), -self._scale(26)), 0.05, math.pi - 0.05, max(2, self._scale(5)))
            else:
                iris_center = (cx + offset_x, eye_y + offset_y)
                pygame.draw.circle(screen, iris_color, iris_center, pupil_radius * 2)
                pygame.draw.circle(screen, (122, 214, 219), iris_center, max(3, int(pupil_radius * 1.25)), max(1, self._scale(2)))
                pygame.draw.circle(screen, (28, 31, 43), iris_center, pupil_radius)
                pygame.draw.circle(screen, (255, 255, 255), (iris_center[0] + pupil_radius // 2, iris_center[1] - pupil_radius // 2), max(3, pupil_radius // 2))
            pygame.draw.arc(screen, (83, 74, 92), rect.inflate(self._scale(8), self._scale(7)), math.pi * 1.03, math.tau - 0.12, max(1, self._scale(3)))

    def _draw_nose(self, screen, pygame, head, mood: str) -> None:
        cx = head.centerx
        top = head.top + self._scale(246)
        bottom = head.top + self._scale(305)
        color = (188, 166, 166) if mood != "sad" else (150, 166, 188)
        pygame.draw.arc(screen, color, pygame.Rect(cx - self._scale(16), top, self._scale(32), bottom - top), math.pi * 1.6, math.tau + math.pi * 0.1, max(1, self._scale(3)))
        pygame.draw.ellipse(screen, color, pygame.Rect(cx - self._scale(15), bottom - self._scale(1), self._scale(10), self._scale(5)))
        pygame.draw.ellipse(screen, color, pygame.Rect(cx + self._scale(5), bottom - self._scale(1), self._scale(10), self._scale(5)))

    def _draw_cheeks(self, screen, pygame, head, mood: str, state: str, now: float) -> None:
        cheek_color = {
            "happy": (225, 139, 150),
            "excited": (238, 152, 116),
            "curious": (132, 190, 184),
            "thinking": (126, 156, 207),
            "sad": (125, 154, 188),
            "listening": (77, 174, 190),
        }.get(mood, (196, 151, 161))
        pulse = 0.5 + 0.5 * math.sin(now * 4.5)
        for side in (-1, 1):
            cx = head.centerx + side * self._scale(118)
            cy = head.top + self._scale(300)
            panel = pygame.Rect(cx - self._scale(48), cy - self._scale(20), self._scale(96), self._scale(40))
            pygame.draw.ellipse(screen, self._mix(cheek_color, (255, 246, 236), 0.34 + pulse * 0.12 if state == "listening" else 0.34), panel)

    def _draw_mouth(self, screen, pygame, head, center_x: int, mood: str, viseme: str, state: str, now: float) -> None:
        y = head.top + self._scale(356)
        self._draw_voice_mouth(screen, pygame, center_x, y, mood, viseme, state, now)

    def _draw_voice_mouth(self, screen, pygame, center_x: int, y: int, mood: str, viseme: str, state: str, now: float) -> None:
        bars = 9
        spacing = max(8, self._scale(15))
        bar_width = max(3, self._scale(6))
        base_height = max(3, self._scale(5))
        max_height = self._scale(34)
        color = (245, 120, 169) if state == "listening" else (246, 226, 238)
        if state == "thinking":
            color = (169, 205, 238)
        elif mood in {"happy", "excited", "curious"}:
            color = (255, 160, 183)
        elif mood == "sad":
            color = (151, 180, 214)
        viseme_level = {"rest": 0.12, "MM": 0.16, "FF": 0.32, "EE": 0.52, "OH": 0.82, "AA": 0.95}.get(viseme, 0.45)
        if viseme != "rest" or state == "speaking":
            level = viseme_level
            speed = 9.0
        elif state == "listening":
            level = 0.24 + 0.08 * math.sin(now * 4.0)
            speed = 4.8
        elif state == "thinking":
            level = 0.2 + 0.06 * math.sin(now * 3.0)
            speed = 3.4
        else:
            level = 0.1
            speed = 2.0
        start_x = center_x - spacing * (bars - 1) // 2
        middle = (bars - 1) / 2
        for index in range(bars):
            falloff = 1.0 - abs(index - middle) / (middle + 1.0) * 0.42
            wave = 0.42 + 0.58 * abs(math.sin(now * speed + index * 0.72))
            height = int(base_height + max_height * max(0.06, level) * wave * falloff)
            x = start_x + index * spacing
            rect = pygame.Rect(x - bar_width // 2, y - height // 2, bar_width, height)
            pygame.draw.rect(screen, self._mix(color, (255, 255, 255), 0.18 * falloff), rect, border_radius=max(2, bar_width // 2))

    def _draw_lip_line(self, screen, pygame, center_x: int, y: int, lip: tuple[int, int, int], shine: tuple[int, int, int], half_width: int, lift: int) -> None:
        pygame.draw.line(screen, lip, (center_x - half_width, y), (center_x + half_width, y), max(3, self._scale(8)))
        pygame.draw.arc(screen, shine, pygame.Rect(center_x - half_width + self._scale(12), y - self._scale(15) - lift, (half_width - self._scale(12)) * 2, self._scale(28)), 0.2, math.pi - 0.2, max(1, self._scale(2)))