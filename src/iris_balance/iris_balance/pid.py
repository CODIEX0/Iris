"""Minimal PID."""
from __future__ import annotations

import time


class PID:
    def __init__(self, kp: float, ki: float, kd: float,
                 output_limit: float = 0.3, integral_limit: float = 0.3) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_limit = output_limit
        self.integral_limit = integral_limit
        self._i = 0.0
        self._prev_err = 0.0
        self._prev_t = time.monotonic()

    def reset(self) -> None:
        self._i = 0.0
        self._prev_err = 0.0
        self._prev_t = time.monotonic()

    def step(self, error: float) -> float:
        now = time.monotonic()
        dt = max(1e-3, now - self._prev_t)
        self._prev_t = now
        self._i = max(-self.integral_limit,
                      min(self.integral_limit, self._i + error * dt))
        d = (error - self._prev_err) / dt
        self._prev_err = error
        out = self.kp * error + self.ki * self._i + self.kd * d
        return max(-self.output_limit, min(self.output_limit, out))