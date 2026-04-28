from __future__ import annotations

import platform
import time
from pathlib import Path
from typing import Any, Optional

from iris_desktop.types import EyeTarget, VisionDetection, VisionScene


MOBILENET_SSD_LABELS = [
    "background",
    "aeroplane",
    "bicycle",
    "bird",
    "boat",
    "bottle",
    "bus",
    "car",
    "cat",
    "chair",
    "cow",
    "dining_table",
    "dog",
    "horse",
    "motorbike",
    "person",
    "potted_plant",
    "sheep",
    "sofa",
    "train",
    "tv_monitor",
]


class CameraTracker:
    def __init__(
        self,
        camera_index: int = 0,
        width: int = 640,
        height: int = 480,
        simulate: bool = False,
        backend: str = "auto",
        detection_interval: float = 0.08,
        object_min_area_ratio: float = 0.025,
        near_object_area_ratio: float = 0.12,
        object_detection: str = "auto",
        object_model_dir: str | Path | None = None,
        object_confidence: float = 0.45,
    ) -> None:
        self.simulate = simulate
        self.backend = "none"
        self.requested_backend = backend
        self.width = width
        self.height = height
        self.detection_interval = detection_interval
        self.object_min_area_ratio = object_min_area_ratio
        self.near_object_area_ratio = near_object_area_ratio
        self.object_detection = (object_detection or "auto").lower()
        self.object_model_dir = Path(object_model_dir or Path.home() / ".iris" / "models" / "object_detection").expanduser()
        self.object_confidence = object_confidence
        self._cv2 = None
        self._capture = None
        self._picamera2 = None
        self._detector = None
        self._cascades: dict[str, Any] = {}
        self._hands = None
        self._object_net = None
        self._motion_model = None
        self._last_target = EyeTarget()
        self._last_scene = VisionScene()
        self._last_detection_at = 0.0
        if not simulate:
            self._open(camera_index)
        if self.simulate:
            print("Camera tracking backend: none")

    @property
    def scene(self) -> VisionScene:
        return self._last_scene

    def describe_scene(self) -> str:
        return self._last_scene.summary

    def _open(self, camera_index: int) -> None:
        candidates = self._backend_order()
        errors = []
        for candidate in candidates:
            try:
                if candidate == "picamera2" and self._open_picamera2(camera_index):
                    print("Camera tracking backend: picamera2")
                    return
                if candidate == "opencv" and self._open_opencv(camera_index):
                    print("Camera tracking backend: opencv")
                    return
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
        if errors:
            print("Camera tracking unavailable: " + "; ".join(errors))
        self.simulate = True

    def _backend_order(self) -> list[str]:
        backend = (self.requested_backend or "auto").lower()
        if backend in {"opencv", "picamera2"}:
            return [backend]
        if platform.system().lower() == "linux":
            return ["picamera2", "opencv"]
        return ["opencv"]

    def _load_detector(self) -> bool:
        import cv2

        self._cv2 = cv2
        cascade_files = {
            "face": "haarcascade_frontalface_default.xml",
            "profile_face": "haarcascade_profileface.xml",
            "upper_body": "haarcascade_upperbody.xml",
            "full_body": "haarcascade_fullbody.xml",
            "eye": "haarcascade_eye_tree_eyeglasses.xml",
            "smile": "haarcascade_smile.xml",
        }
        self._cascades = {}
        for label, file_name in cascade_files.items():
            cascade_path = Path(cv2.data.haarcascades) / file_name
            if not cascade_path.exists():
                continue
            detector = cv2.CascadeClassifier(str(cascade_path))
            if not detector.empty():
                self._cascades[label] = detector
        self._detector = self._cascades.get("face")
        self._motion_model = cv2.createBackgroundSubtractorMOG2(history=90, varThreshold=32, detectShadows=False)
        self._hands = self._create_hands()
        self._object_net = self._load_object_detector()
        return True

    def _load_object_detector(self):
        if self.object_detection == "off":
            return None
        prototxt = self.object_model_dir / "MobileNetSSD_deploy.prototxt"
        model = self.object_model_dir / "MobileNetSSD_deploy.caffemodel"
        if not prototxt.exists() or not model.exists():
            if self.object_detection == "on":
                print(f"Object recognition model missing under {self.object_model_dir}")
            return None
        try:
            net = self._cv2.dnn.readNetFromCaffe(str(prototxt), str(model))
            print("Object recognition backend: MobileNet SSD")
            return net
        except Exception as exc:
            if self.object_detection == "on":
                print(f"Object recognition unavailable: {exc}")
            return None

    def _create_hands(self):
        try:
            import mediapipe as mp
        except Exception:
            return None
        return mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.55,
        )

    def _open_opencv(self, camera_index: int) -> bool:
        if self._detector is None and not self._load_detector():
            return False
        assert self._cv2 is not None
        api_preference = self._cv2.CAP_DSHOW if platform.system().lower() == "windows" else 0
        capture = self._cv2.VideoCapture(camera_index, api_preference) if api_preference else self._cv2.VideoCapture(camera_index)
        if not capture.isOpened() and api_preference:
            capture.release()
            capture = self._cv2.VideoCapture(camera_index)
        if not capture.isOpened():
            capture.release()
            return False
        capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._capture = capture
        self.backend = "opencv"
        self.simulate = False
        return True

    def _open_picamera2(self, camera_index: int) -> bool:
        if self._detector is None and not self._load_detector():
            return False
        from picamera2 import Picamera2

        camera = Picamera2(camera_num=camera_index)
        config = camera.create_preview_configuration(main={"size": (self.width, self.height), "format": "RGB888"})
        camera.configure(config)
        camera.start()
        self._picamera2 = camera
        self.backend = "picamera2"
        self.simulate = False
        return True

    def poll(self) -> EyeTarget:
        if self.simulate or self._cv2 is None:
            self._last_scene = VisionScene(summary="camera unavailable")
            return EyeTarget()
        now = time.monotonic()
        if now - self._last_detection_at < self.detection_interval:
            return self._last_target
        self._last_detection_at = now
        frame = self._read_frame()
        if frame is None:
            self._last_target = self._settle_to_center()
            self._last_scene = VisionScene(summary="camera frame unavailable")
            return self._last_target
        height, width = frame.shape[:2]
        gray = self._frame_to_gray(frame)
        face_rects = self._detect_cascade_rects("face", gray, min_size=(60, 60))
        self._last_scene = self._analyze_scene(frame, gray, face_rects)
        if not face_rects:
            self._last_target = self._settle_to_center()
            return self._last_target
        left, top, box_width, box_height = max(face_rects, key=lambda item: item[2] * item[3])
        target = EyeTarget((left + box_width * 0.5) / width, (top + box_height * 0.45) / height)
        self._last_target = self._smooth(target)
        return self._last_target

    def _analyze_scene(self, frame: Any, gray: Any, face_rects: list[tuple[int, int, int, int]]) -> VisionScene:
        height, width = gray.shape[:2]
        objects: list[VisionDetection] = []

        for rect in face_rects:
            objects.append(self._detection_from_rect("face", rect, width, height, 0.9))
        for rect in self._detect_profile_faces(gray, width):
            if not self._overlaps_any(rect, face_rects, 0.35):
                objects.append(self._detection_from_rect("profile_face", rect, width, height, 0.72))
        for label, min_size, confidence in (("upper_body", (70, 90), 0.64), ("full_body", (70, 130), 0.62)):
            for rect in self._detect_cascade_rects(label, gray, scale_factor=1.05, min_neighbors=4, min_size=min_size):
                objects.append(self._detection_from_rect(label, rect, width, height, confidence))
        for face_rect in face_rects:
            objects.extend(self._detect_face_parts(gray, face_rect, width, height))
        objects.extend(self._detect_hands(frame, width, height))
        objects.extend(self._detect_named_objects(frame, width, height))

        edges = self._cv2.Canny(gray, 60, 150)
        motion_level = self._motion_level(gray, width, height)
        edge_density = float(self._cv2.countNonZero(edges)) / float(max(1, width * height))
        objects.extend(self._detect_near_objects(edges, width, height))

        objects = sorted(objects, key=lambda item: (not item.near, -item.area, item.label))[:18]
        face_count = sum(1 for item in objects if item.label in {"face", "profile_face"})
        body_count = sum(1 for item in objects if item.label in {"upper_body", "full_body"})
        person_count = sum(1 for item in objects if item.label == "person")
        hand_count = sum(1 for item in objects if item.label == "hand")
        nearby_object_count = sum(1 for item in objects if item.near or item.label == "near_object")
        people_count = max(face_count, body_count, person_count)
        brightness = float(gray.mean()) / 255.0
        summary = self._summarize_scene(objects, people_count, face_count, body_count, person_count, hand_count, nearby_object_count, brightness, motion_level)
        return VisionScene(
            objects=objects,
            people_count=people_count,
            face_count=face_count,
            body_count=body_count,
            hand_count=hand_count,
            nearby_object_count=nearby_object_count,
            brightness=brightness,
            motion_level=motion_level,
            edge_density=edge_density,
            summary=summary,
        )

    def _detect_cascade_rects(
        self,
        label: str,
        gray: Any,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: tuple[int, int] = (40, 40),
    ) -> list[tuple[int, int, int, int]]:
        detector = self._cascades.get(label)
        if detector is None:
            return []
        rects = detector.detectMultiScale(gray, scaleFactor=scale_factor, minNeighbors=min_neighbors, minSize=min_size)
        return [tuple(int(value) for value in rect) for rect in rects]

    def _detect_profile_faces(self, gray: Any, frame_width: int) -> list[tuple[int, int, int, int]]:
        rects = self._detect_cascade_rects("profile_face", gray, min_neighbors=4, min_size=(55, 55))
        if self._cascades.get("profile_face") is None:
            return rects
        flipped = self._cv2.flip(gray, 1)
        for left, top, box_width, box_height in self._detect_cascade_rects("profile_face", flipped, min_neighbors=4, min_size=(55, 55)):
            rects.append((frame_width - left - box_width, top, box_width, box_height))
        return rects

    def _detect_face_parts(self, gray: Any, face_rect: tuple[int, int, int, int], frame_width: int, frame_height: int) -> list[VisionDetection]:
        left, top, box_width, box_height = face_rect
        detections: list[VisionDetection] = []
        upper_face = gray[top : top + int(box_height * 0.62), left : left + box_width]
        lower_top = top + int(box_height * 0.45)
        lower_face = gray[lower_top : top + box_height, left : left + box_width]
        for eye_left, eye_top, eye_width, eye_height in self._detect_cascade_rects("eye", upper_face, min_neighbors=5, min_size=(14, 14))[:2]:
            detections.append(self._detection_from_rect("eye", (left + eye_left, top + eye_top, eye_width, eye_height), frame_width, frame_height, 0.68))
        for smile_left, smile_top, smile_width, smile_height in self._detect_cascade_rects("smile", lower_face, scale_factor=1.7, min_neighbors=18, min_size=(22, 12))[:1]:
            detections.append(self._detection_from_rect("smile", (left + smile_left, lower_top + smile_top, smile_width, smile_height), frame_width, frame_height, 0.58))
        return detections

    def _detect_named_objects(self, frame: Any, frame_width: int, frame_height: int) -> list[VisionDetection]:
        if self._object_net is None:
            return []
        bgr = self._frame_to_bgr(frame)
        blob = self._cv2.dnn.blobFromImage(bgr, 0.007843, (300, 300), 127.5)
        self._object_net.setInput(blob)
        detections = self._object_net.forward()
        objects: list[VisionDetection] = []
        for index in range(detections.shape[2]):
            confidence = float(detections[0, 0, index, 2])
            if confidence < self.object_confidence:
                continue
            class_id = int(detections[0, 0, index, 1])
            if class_id <= 0 or class_id >= len(MOBILENET_SSD_LABELS):
                continue
            left = int(max(0.0, detections[0, 0, index, 3]) * frame_width)
            top = int(max(0.0, detections[0, 0, index, 4]) * frame_height)
            right = int(min(1.0, detections[0, 0, index, 5]) * frame_width)
            bottom = int(min(1.0, detections[0, 0, index, 6]) * frame_height)
            box_width = max(1, right - left)
            box_height = max(1, bottom - top)
            objects.append(self._detection_from_rect(MOBILENET_SSD_LABELS[class_id], (left, top, box_width, box_height), frame_width, frame_height, confidence))
        return self._dedupe_named_objects(objects)

    def _dedupe_named_objects(self, objects: list[VisionDetection]) -> list[VisionDetection]:
        kept: list[VisionDetection] = []
        for item in sorted(objects, key=lambda detection: detection.confidence, reverse=True):
            if any(item.label == other.label and self._normalized_iou(item, other) > 0.42 for other in kept):
                continue
            kept.append(item)
        return kept[:10]

    def _detect_hands(self, frame: Any, frame_width: int, frame_height: int) -> list[VisionDetection]:
        if self._hands is None:
            return []
        rgb = self._frame_to_rgb(frame)
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            return []
        detections: list[VisionDetection] = []
        for hand in result.multi_hand_landmarks[:2]:
            min_x = max(0.0, min(point.x for point in hand.landmark))
            max_x = min(1.0, max(point.x for point in hand.landmark))
            min_y = max(0.0, min(point.y for point in hand.landmark))
            max_y = min(1.0, max(point.y for point in hand.landmark))
            left = int(min_x * frame_width)
            top = int(min_y * frame_height)
            box_width = max(1, int((max_x - min_x) * frame_width))
            box_height = max(1, int((max_y - min_y) * frame_height))
            detections.append(self._detection_from_rect("hand", (left, top, box_width, box_height), frame_width, frame_height, 0.74))
        return detections

    def _detect_near_objects(self, edges: Any, frame_width: int, frame_height: int) -> list[VisionDetection]:
        kernel = self._cv2.getStructuringElement(self._cv2.MORPH_RECT, (5, 5))
        closed = self._cv2.morphologyEx(edges, self._cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _hierarchy = self._cv2.findContours(closed, self._cv2.RETR_EXTERNAL, self._cv2.CHAIN_APPROX_SIMPLE)
        detections: list[VisionDetection] = []
        frame_area = float(max(1, frame_width * frame_height))
        for contour in contours:
            contour_area = float(self._cv2.contourArea(contour))
            area_ratio = contour_area / frame_area
            if area_ratio < self.object_min_area_ratio:
                continue
            left, top, box_width, box_height = self._cv2.boundingRect(contour)
            if box_width > frame_width * 0.94 and box_height > frame_height * 0.94:
                continue
            label = "near_object" if area_ratio >= self.near_object_area_ratio else "object"
            confidence = min(0.84, 0.36 + area_ratio * 3.0)
            detections.append(self._detection_from_rect(label, (left, top, box_width, box_height), frame_width, frame_height, confidence, area_ratio))
        return sorted(detections, key=lambda item: item.area, reverse=True)[:6]

    def _motion_level(self, gray: Any, frame_width: int, frame_height: int) -> float:
        if self._motion_model is None:
            return 0.0
        mask = self._motion_model.apply(gray)
        _threshold_value, mask = self._cv2.threshold(mask, 200, 255, self._cv2.THRESH_BINARY)
        return float(self._cv2.countNonZero(mask)) / float(max(1, frame_width * frame_height))

    def _detection_from_rect(
        self,
        label: str,
        rect: tuple[int, int, int, int],
        frame_width: int,
        frame_height: int,
        confidence: float,
        contour_area_ratio: float | None = None,
    ) -> VisionDetection:
        left, top, box_width, box_height = rect
        area = contour_area_ratio if contour_area_ratio is not None else float(box_width * box_height) / float(max(1, frame_width * frame_height))
        return VisionDetection(
            label=label,
            x=float(left) / frame_width,
            y=float(top) / frame_height,
            width=float(box_width) / frame_width,
            height=float(box_height) / frame_height,
            confidence=confidence,
            area=area,
            zone=self._zone_for_rect(left, top, box_width, box_height, frame_width, frame_height),
            near=area >= self.near_object_area_ratio or label == "near_object",
        )

    def _zone_for_rect(self, left: int, top: int, box_width: int, box_height: int, frame_width: int, frame_height: int) -> str:
        center_x = (left + box_width * 0.5) / max(1, frame_width)
        center_y = (top + box_height * 0.5) / max(1, frame_height)
        horizontal = "left" if center_x < 0.38 else "right" if center_x > 0.62 else "center"
        vertical = "upper" if center_y < 0.36 else "lower" if center_y > 0.66 else "middle"
        return horizontal if vertical == "middle" else f"{vertical}_{horizontal}"

    def _overlaps_any(self, rect: tuple[int, int, int, int], others: list[tuple[int, int, int, int]], threshold: float) -> bool:
        return any(self._intersection_over_union(rect, other) >= threshold for other in others)

    def _normalized_iou(self, detection_a: VisionDetection, detection_b: VisionDetection) -> float:
        left_a, top_a = detection_a.x, detection_a.y
        right_a, bottom_a = detection_a.x + detection_a.width, detection_a.y + detection_a.height
        left_b, top_b = detection_b.x, detection_b.y
        right_b, bottom_b = detection_b.x + detection_b.width, detection_b.y + detection_b.height
        inter_left = max(left_a, left_b)
        inter_top = max(top_a, top_b)
        inter_right = min(right_a, right_b)
        inter_bottom = min(bottom_a, bottom_b)
        inter_area = max(0.0, inter_right - inter_left) * max(0.0, inter_bottom - inter_top)
        union_area = detection_a.width * detection_a.height + detection_b.width * detection_b.height - inter_area
        return inter_area / max(1e-6, union_area)

    def _intersection_over_union(self, rect_a: tuple[int, int, int, int], rect_b: tuple[int, int, int, int]) -> float:
        left_a, top_a, width_a, height_a = rect_a
        left_b, top_b, width_b, height_b = rect_b
        inter_left = max(left_a, left_b)
        inter_top = max(top_a, top_b)
        inter_right = min(left_a + width_a, left_b + width_b)
        inter_bottom = min(top_a + height_a, top_b + height_b)
        inter_area = max(0, inter_right - inter_left) * max(0, inter_bottom - inter_top)
        union_area = width_a * height_a + width_b * height_b - inter_area
        return float(inter_area) / float(max(1, union_area))

    def _summarize_scene(
        self,
        objects: list[VisionDetection],
        people_count: int,
        face_count: int,
        body_count: int,
        person_count: int,
        hand_count: int,
        nearby_object_count: int,
        brightness: float,
        motion_level: float,
    ) -> str:
        parts: list[str] = []
        if face_count:
            parts.append(f"{face_count} face{'s' if face_count != 1 else ''}")
        if body_count:
            parts.append(f"{body_count} body shape{'s' if body_count != 1 else ''}")
        if person_count and not face_count and not body_count:
            parts.append(f"{person_count} person{'s' if person_count != 1 else ''}")
        if hand_count:
            parts.append(f"{hand_count} hand{'s' if hand_count != 1 else ''}")
        named = [item.label.replace("_", " ") for item in objects if item.label not in {"face", "profile_face", "upper_body", "full_body", "person", "eye", "smile", "hand", "object", "near_object"}]
        if named:
            parts.append(", ".join(named[:4]))
        if people_count and not face_count and not body_count:
            parts.append(f"{people_count} person-shaped region{'s' if people_count != 1 else ''}")
        if nearby_object_count:
            parts.append(f"{nearby_object_count} nearby object{'s' if nearby_object_count != 1 else ''}")
        if not parts:
            parts.append("no clear people or nearby objects")
        light = "bright" if brightness > 0.62 else "dim" if brightness < 0.28 else "moderate"
        motion = "high" if motion_level > 0.12 else "some" if motion_level > 0.035 else "low"
        strongest = next((item for item in objects if item.near), objects[0] if objects else None)
        focus = f"; closest focus is {strongest.label.replace('_', ' ')} at {strongest.zone}" if strongest is not None else ""
        return f"I see {', '.join(parts)}{focus}; light is {light}; motion is {motion}."

    def _read_frame(self) -> Optional[Any]:
        if self.backend == "picamera2" and self._picamera2 is not None:
            return self._picamera2.capture_array()
        if self._capture is not None:
            ok, frame = self._capture.read()
            return frame if ok else None
        return None

    def _frame_to_gray(self, frame: Any) -> Any:
        assert self._cv2 is not None
        if len(frame.shape) == 2:
            return frame
        channels = frame.shape[2]
        if channels == 4:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_BGRA2GRAY)
        if self.backend == "picamera2":
            return self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2GRAY)
        return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)

    def _frame_to_bgr(self, frame: Any) -> Any:
        assert self._cv2 is not None
        if len(frame.shape) == 2:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_GRAY2BGR)
        channels = frame.shape[2]
        if channels == 4:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_BGRA2BGR)
        if self.backend == "picamera2":
            return self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2BGR)
        return frame

    def _frame_to_rgb(self, frame: Any) -> Any:
        assert self._cv2 is not None
        if len(frame.shape) == 2:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_GRAY2RGB)
        channels = frame.shape[2]
        if channels == 4:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_BGRA2RGB)
        if self.backend == "picamera2":
            return frame
        return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)

    def _smooth(self, target: EyeTarget) -> EyeTarget:
        alpha = 0.35
        return EyeTarget(
            self._last_target.x + (target.x - self._last_target.x) * alpha,
            self._last_target.y + (target.y - self._last_target.y) * alpha,
        )

    def _settle_to_center(self) -> EyeTarget:
        return self._smooth(EyeTarget())

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        if self._picamera2 is not None:
            self._picamera2.stop()
            self._picamera2.close()
        if self._hands is not None:
            self._hands.close()