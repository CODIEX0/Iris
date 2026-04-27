"""Complementary filter for MPU6050-style gyro + accelerometer fusion."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Attitude:
    roll: float = 0.0
    pitch: float = 0.0


class ComplementaryFilter:
    def __init__(self, alpha: float = 0.98) -> None:
        self.alpha = alpha
        self.att = Attitude()

    def update(self, ax: float, ay: float, az: float,
               gx: float, gy: float, dt: float) -> Attitude:
        accel_roll = math.atan2(ay, math.sqrt(ax * ax + az * az))
        accel_pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az))
        self.att.roll = self.alpha * (self.att.roll + gx * dt) + (1.0 - self.alpha) * accel_roll
        self.att.pitch = self.alpha * (self.att.pitch + gy * dt) + (1.0 - self.alpha) * accel_pitch
        return self.att