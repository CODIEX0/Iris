from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EyeTarget:
    x: float = 0.5
    y: float = 0.4


@dataclass
class Reply:
    text: str
    emotion: str = "neutral"


@dataclass
class Touch:
    zone: str
    action: str


@dataclass
class VisionDetection:
    label: str
    x: float
    y: float
    width: float
    height: float
    confidence: float = 0.0
    area: float = 0.0
    zone: str = "center"
    near: bool = False


@dataclass
class VisionScene:
    objects: list[VisionDetection] = field(default_factory=list)
    people_count: int = 0
    face_count: int = 0
    body_count: int = 0
    hand_count: int = 0
    nearby_object_count: int = 0
    brightness: float = 0.0
    motion_level: float = 0.0
    edge_density: float = 0.0
    summary: str = "camera idle"