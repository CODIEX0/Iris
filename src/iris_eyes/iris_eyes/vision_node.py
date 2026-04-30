"""Camera perception node for faces and simple hand gestures."""
from __future__ import annotations

import platform
from pathlib import Path
from typing import Any, List, Optional

import rclpy
from geometry_msgs.msg import Point
from rclpy.node import Node

from iris_msgs.msg import FaceDetection, FaceDetectionArray, Gesture, VisionObject, VisionScene


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

SUMMARY_EXCLUDED_OBJECT_LABELS = {"face", "profile_face", "upper_body", "full_body", "person", "eye", "smile", "hand", "object", "near_object"}


def _try_import_cv2():
    try:
        import cv2
    except Exception:
        return None
    return cv2


def _try_import_mediapipe():
    try:
        import mediapipe as mp
    except Exception:
        return None
    return mp


def _format_object_counts(objects: List[VisionObject], limit: int) -> List[str]:
    counts: dict[str, int] = {}
    ordered_labels: List[str] = []
    for item in objects:
        label = item.label.replace("_", " ")
        if label not in counts:
            ordered_labels.append(label)
            counts[label] = 0
        counts[label] += 1
    return [_format_count(label, counts[label]) for label in ordered_labels[:limit]]


def _format_count(label: str, count: int) -> str:
    if count == 1:
        return label
    if label.endswith("s"):
        return f"{count} {label}"
    return f"{count} {label}s"


class VisionNode(Node):
    def __init__(self) -> None:
        super().__init__("vision_node")
        self.declare_parameter("camera_index", 0)
        self.declare_parameter("camera_backend", "auto")
        self.declare_parameter("frame_width", 640)
        self.declare_parameter("frame_height", 480)
        self.declare_parameter("rate_hz", 15.0)
        self.declare_parameter("simulate", False)
        self.declare_parameter("show_preview", False)
        self.declare_parameter("min_face_size_px", 60)
        self.declare_parameter("gesture_confidence", 0.82)
        self.declare_parameter("scene_detection_enabled", True)
        self.declare_parameter("object_min_area_ratio", 0.025)
        self.declare_parameter("near_object_area_ratio", 0.12)
        self.declare_parameter("object_detection", "on")
        self.declare_parameter("object_model_dir", "~/iris_models/object_detection")
        self.declare_parameter("object_confidence", 0.35)

        self.simulate = bool(self.get_parameter("simulate").value)
        self.show_preview = bool(self.get_parameter("show_preview").value)
        self.scene_detection_enabled = bool(self.get_parameter("scene_detection_enabled").value)
        self.object_min_area_ratio = float(self.get_parameter("object_min_area_ratio").value)
        self.near_object_area_ratio = float(self.get_parameter("near_object_area_ratio").value)
        self.object_detection = str(self.get_parameter("object_detection").value or "auto").lower()
        self.object_model_dir = Path(str(self.get_parameter("object_model_dir").value or "~/iris_models/object_detection")).expanduser()
        self.object_confidence = float(self.get_parameter("object_confidence").value)
        self._cv2 = _try_import_cv2()
        self._mp = _try_import_mediapipe()
        self._hands = self._create_hands()
        self._cascades: dict[str, Any] = {}
        self._motion_model = None
        self._object_net = None
        self._face_detector = self._create_face_detector()
        self._camera_backend = "none"
        self._picamera2 = None
        self._capture = self._open_camera()

        self._faces_pub = self.create_publisher(FaceDetectionArray, "/vision/faces", 10)
        self._gesture_pub = self.create_publisher(Gesture, "/gesture/detected", 10)
        self._scene_pub = self.create_publisher(VisionScene, "/vision/scene", 10)

        rate_hz = float(self.get_parameter("rate_hz").value)
        self.create_timer(1.0 / rate_hz, self._tick)
        mode = "simulated" if self.simulate or (self._capture is None and self._picamera2 is None) else self._camera_backend
        self.get_logger().info(f"vision_node up in {mode} mode @ {rate_hz} Hz")

    def _create_hands(self):
        if self._mp is None:
            self.get_logger().warn("mediapipe unavailable; hand gestures disabled")
            return None
        return self._mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.55,
        )

    def _create_face_detector(self):
        if self._cv2 is None:
            self.get_logger().warn("opencv unavailable; using simulated/no face detection")
            return None
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
            detector = self._cv2.CascadeClassifier(self._cv2.data.haarcascades + file_name)
            if not detector.empty():
                self._cascades[label] = detector
        self._motion_model = self._cv2.createBackgroundSubtractorMOG2(history=90, varThreshold=32, detectShadows=False)
        self._object_net = self._load_object_detector()
        detector = self._cascades.get("face")
        if detector is None:
            self.get_logger().warn("OpenCV face cascade not found; face detection disabled")
            return None
        return detector

    def _load_object_detector(self):
        if self.object_detection == "off":
            return None
        prototxt = self.object_model_dir / "MobileNetSSD_deploy.prototxt"
        model = self.object_model_dir / "MobileNetSSD_deploy.caffemodel"
        if not prototxt.exists() or not model.exists():
            if self.object_detection == "on":
                self.get_logger().warn(f"object recognition model missing under {self.object_model_dir}")
            return None
        try:
            net = self._cv2.dnn.readNetFromCaffe(str(prototxt), str(model))
            self.get_logger().info("object recognition backend: MobileNet SSD")
            return net
        except Exception as exc:
            if self.object_detection == "on":
                self.get_logger().warn(f"object recognition unavailable: {exc}")
            return None

    def _open_camera(self):
        if self.simulate or self._cv2 is None:
            return None
        index = int(self.get_parameter("camera_index").value)
        errors = []
        for backend in self._backend_order():
            try:
                if backend == "picamera2" and self._open_picamera2(index):
                    return None
                if backend == "opencv":
                    capture = self._open_opencv(index)
                    if capture is not None:
                        return capture
            except Exception as exc:
                errors.append(f"{backend}: {exc}")
        detail = "; ".join(errors) if errors else f"camera {index} unavailable"
        self.get_logger().warn(f"{detail}; publishing simulated faces")
        self.simulate = True
        return None

    def _backend_order(self) -> List[str]:
        backend = str(self.get_parameter("camera_backend").value or "auto").lower()
        if backend in {"opencv", "picamera2"}:
            return [backend]
        if platform.system().lower() == "linux":
            return ["picamera2", "opencv"]
        return ["opencv"]

    def _open_opencv(self, index: int):
        capture = self._cv2.VideoCapture(index)
        if not capture.isOpened():
            capture.release()
            return None
        capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, int(self.get_parameter("frame_width").value))
        capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, int(self.get_parameter("frame_height").value))
        self._camera_backend = "opencv"
        return capture

    def _open_picamera2(self, index: int) -> bool:
        from picamera2 import Picamera2

        width = int(self.get_parameter("frame_width").value)
        height = int(self.get_parameter("frame_height").value)
        camera = Picamera2(camera_num=index)
        config = camera.create_preview_configuration(main={"size": (width, height), "format": "RGB888"})
        camera.configure(config)
        camera.start()
        self._picamera2 = camera
        self._camera_backend = "picamera2"
        return True

    def _tick(self) -> None:
        frame = self._read_frame()
        if frame is None:
            self._publish_simulated()
            return

        faces = self._detect_faces(frame)
        gesture = self._detect_gesture(frame)
        scene = self._detect_scene(frame, faces, gesture) if self.scene_detection_enabled else None
        self._publish_faces(faces)
        if gesture is not None:
            self._gesture_pub.publish(gesture)
        if scene is not None:
            self._scene_pub.publish(scene)
        if self.show_preview:
            self._draw_preview(frame, faces, gesture, scene)

    def _read_frame(self):
        if self._picamera2 is not None:
            return self._picamera2.capture_array()
        if self._capture is None:
            return None
        ok, frame = self._capture.read()
        if not ok:
            self.get_logger().warn("camera frame read failed; switching to simulated faces")
            self.simulate = True
            return None
        return frame

    def _publish_simulated(self) -> None:
        faces = []
        if self.simulate:
            face = FaceDetection()
            face.id = 0
            face.x = 0.36
            face.y = 0.18
            face.width = 0.28
            face.height = 0.42
            face.confidence = 1.0
            face.gaze_target = Point(x=0.5, y=0.4, z=0.0)
            faces.append(face)
        self._publish_faces(faces)
        if self.scene_detection_enabled:
            scene = VisionScene()
            scene.header.stamp = self.get_clock().now().to_msg()
            scene.header.frame_id = "camera"
            scene.people_count = len(faces)
            scene.face_count = len(faces)
            scene.summary = "I see a simulated face for testing; camera input is unavailable."
            self._scene_pub.publish(scene)

    def _detect_faces(self, frame) -> List[FaceDetection]:
        if self._cv2 is None or self._face_detector is None:
            return []
        height, width = frame.shape[:2]
        gray = self._frame_to_gray(frame)
        min_size = int(self.get_parameter("min_face_size_px").value)
        rects = self._face_detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(min_size, min_size),
        )
        faces: List[FaceDetection] = []
        for face_id, (x, y, w, h) in enumerate(rects):
            detection = FaceDetection()
            detection.id = face_id
            detection.x = float(x) / width
            detection.y = float(y) / height
            detection.width = float(w) / width
            detection.height = float(h) / height
            detection.confidence = 0.9
            detection.gaze_target = Point(
                x=detection.x + detection.width * 0.5,
                y=detection.y + detection.height * 0.45,
                z=0.0,
            )
            faces.append(detection)
        return faces

    def _detect_scene(self, frame, faces: List[FaceDetection], gesture: Optional[Gesture]) -> VisionScene:
        gray = self._frame_to_gray(frame)
        frame_height, frame_width = gray.shape[:2]
        objects: List[VisionObject] = []
        face_rects = [self._rect_from_face(face, frame_width, frame_height) for face in faces]

        for rect in face_rects:
            objects.append(self._object_from_rect("face", rect, frame_width, frame_height, 0.9))
        for rect in self._detect_profile_faces(gray, frame_width):
            if not self._overlaps_any(rect, face_rects, 0.35):
                objects.append(self._object_from_rect("profile_face", rect, frame_width, frame_height, 0.72))
        for label, min_size, confidence in (("upper_body", (70, 90), 0.64), ("full_body", (70, 130), 0.62)):
            for rect in self._detect_cascade_rects(label, gray, scale_factor=1.05, min_neighbors=4, min_size=min_size):
                objects.append(self._object_from_rect(label, rect, frame_width, frame_height, confidence))
        for rect in face_rects:
            objects.extend(self._detect_face_parts(gray, rect, frame_width, frame_height))
        if gesture is not None:
            objects.append(self._object_from_gesture(gesture))
        objects.extend(self._detect_named_objects(frame, frame_width, frame_height))

        edges = self._cv2.Canny(gray, 60, 150)
        motion_level = self._motion_level(gray, frame_width, frame_height)
        edge_density = float(self._cv2.countNonZero(edges)) / float(max(1, frame_width * frame_height))
        objects.extend(self._detect_near_objects(edges, frame_width, frame_height))
        objects = sorted(objects, key=lambda item: (not item.near, -item.area, item.label))[:18]

        scene = VisionScene()
        scene.header.stamp = self.get_clock().now().to_msg()
        scene.header.frame_id = "camera"
        scene.objects = objects
        scene.face_count = sum(1 for item in objects if item.label in {"face", "profile_face"})
        scene.body_count = sum(1 for item in objects if item.label in {"upper_body", "full_body"})
        person_count = sum(1 for item in objects if item.label == "person")
        scene.hand_count = sum(1 for item in objects if item.label == "hand")
        scene.nearby_object_count = sum(1 for item in objects if item.near or item.label == "near_object")
        scene.people_count = max(scene.face_count, scene.body_count, person_count)
        scene.brightness = float(gray.mean()) / 255.0
        scene.motion_level = motion_level
        scene.edge_density = edge_density
        scene.summary = self._summarize_scene(objects, scene.people_count, scene.face_count, scene.body_count, person_count, scene.hand_count, scene.nearby_object_count, scene.brightness, motion_level)
        return scene

    def _detect_cascade_rects(
        self,
        label: str,
        gray,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: tuple[int, int] = (40, 40),
    ) -> List[tuple[int, int, int, int]]:
        detector = self._cascades.get(label)
        if detector is None:
            return []
        rects = detector.detectMultiScale(gray, scaleFactor=scale_factor, minNeighbors=min_neighbors, minSize=min_size)
        return [tuple(int(value) for value in rect) for rect in rects]

    def _detect_profile_faces(self, gray, frame_width: int) -> List[tuple[int, int, int, int]]:
        rects = self._detect_cascade_rects("profile_face", gray, min_neighbors=4, min_size=(55, 55))
        if self._cascades.get("profile_face") is None:
            return rects
        flipped = self._cv2.flip(gray, 1)
        for left, top, box_width, box_height in self._detect_cascade_rects("profile_face", flipped, min_neighbors=4, min_size=(55, 55)):
            rects.append((frame_width - left - box_width, top, box_width, box_height))
        return rects

    def _detect_face_parts(self, gray, face_rect: tuple[int, int, int, int], frame_width: int, frame_height: int) -> List[VisionObject]:
        left, top, box_width, box_height = face_rect
        detections: List[VisionObject] = []
        upper_face = gray[top : top + int(box_height * 0.62), left : left + box_width]
        lower_top = top + int(box_height * 0.45)
        lower_face = gray[lower_top : top + box_height, left : left + box_width]
        for eye_left, eye_top, eye_width, eye_height in self._detect_cascade_rects("eye", upper_face, min_neighbors=5, min_size=(14, 14))[:2]:
            detections.append(self._object_from_rect("eye", (left + eye_left, top + eye_top, eye_width, eye_height), frame_width, frame_height, 0.68))
        for smile_left, smile_top, smile_width, smile_height in self._detect_cascade_rects("smile", lower_face, scale_factor=1.7, min_neighbors=18, min_size=(22, 12))[:1]:
            detections.append(self._object_from_rect("smile", (left + smile_left, lower_top + smile_top, smile_width, smile_height), frame_width, frame_height, 0.58))
        return detections

    def _detect_named_objects(self, frame, frame_width: int, frame_height: int) -> List[VisionObject]:
        if self._object_net is None:
            return []
        bgr = self._frame_to_bgr(frame)
        blob = self._cv2.dnn.blobFromImage(bgr, 0.007843, (300, 300), 127.5)
        self._object_net.setInput(blob)
        detections = self._object_net.forward()
        objects: List[VisionObject] = []
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
            objects.append(self._object_from_rect(MOBILENET_SSD_LABELS[class_id], (left, top, box_width, box_height), frame_width, frame_height, confidence))
        return self._dedupe_named_objects(objects)

    def _dedupe_named_objects(self, objects: List[VisionObject]) -> List[VisionObject]:
        kept: List[VisionObject] = []
        for item in sorted(objects, key=lambda detection: detection.confidence, reverse=True):
            if any(item.label == other.label and self._normalized_iou(item, other) > 0.42 for other in kept):
                continue
            kept.append(item)
        return kept[:10]

    def _detect_near_objects(self, edges, frame_width: int, frame_height: int) -> List[VisionObject]:
        kernel = self._cv2.getStructuringElement(self._cv2.MORPH_RECT, (5, 5))
        closed = self._cv2.morphologyEx(edges, self._cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _hierarchy = self._cv2.findContours(closed, self._cv2.RETR_EXTERNAL, self._cv2.CHAIN_APPROX_SIMPLE)
        detections: List[VisionObject] = []
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
            detections.append(self._object_from_rect(label, (left, top, box_width, box_height), frame_width, frame_height, confidence, area_ratio))
        return sorted(detections, key=lambda item: item.area, reverse=True)[:6]

    def _motion_level(self, gray, frame_width: int, frame_height: int) -> float:
        if self._motion_model is None:
            return 0.0
        mask = self._motion_model.apply(gray)
        _threshold_value, mask = self._cv2.threshold(mask, 200, 255, self._cv2.THRESH_BINARY)
        return float(self._cv2.countNonZero(mask)) / float(max(1, frame_width * frame_height))

    def _rect_from_face(self, face: FaceDetection, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        return (
            int(face.x * frame_width),
            int(face.y * frame_height),
            int(face.width * frame_width),
            int(face.height * frame_height),
        )

    def _object_from_gesture(self, gesture: Gesture) -> VisionObject:
        size = 0.14
        detection = VisionObject()
        detection.label = "hand"
        detection.x = max(0.0, float(gesture.location.x) - size * 0.5)
        detection.y = max(0.0, float(gesture.location.y) - size * 0.5)
        detection.width = size
        detection.height = size
        detection.confidence = float(gesture.confidence)
        detection.area = size * size
        detection.zone = self._zone_for_normalized_rect(detection.x, detection.y, detection.width, detection.height)
        detection.near = False
        return detection

    def _object_from_rect(
        self,
        label: str,
        rect: tuple[int, int, int, int],
        frame_width: int,
        frame_height: int,
        confidence: float,
        contour_area_ratio: float | None = None,
    ) -> VisionObject:
        left, top, box_width, box_height = rect
        area = contour_area_ratio if contour_area_ratio is not None else float(box_width * box_height) / float(max(1, frame_width * frame_height))
        detection = VisionObject()
        detection.label = label
        detection.x = float(left) / frame_width
        detection.y = float(top) / frame_height
        detection.width = float(box_width) / frame_width
        detection.height = float(box_height) / frame_height
        detection.confidence = confidence
        detection.area = area
        detection.zone = self._zone_for_normalized_rect(detection.x, detection.y, detection.width, detection.height)
        detection.near = area >= self.near_object_area_ratio or label == "near_object"
        return detection

    def _zone_for_normalized_rect(self, left: float, top: float, box_width: float, box_height: float) -> str:
        center_x = left + box_width * 0.5
        center_y = top + box_height * 0.5
        horizontal = "left" if center_x < 0.38 else "right" if center_x > 0.62 else "center"
        vertical = "upper" if center_y < 0.36 else "lower" if center_y > 0.66 else "middle"
        return horizontal if vertical == "middle" else f"{vertical}_{horizontal}"

    def _overlaps_any(self, rect: tuple[int, int, int, int], others: List[tuple[int, int, int, int]], threshold: float) -> bool:
        return any(self._intersection_over_union(rect, other) >= threshold for other in others)

    def _normalized_iou(self, detection_a: VisionObject, detection_b: VisionObject) -> float:
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
        objects: List[VisionObject],
        people_count: int,
        face_count: int,
        body_count: int,
        person_count: int,
        hand_count: int,
        nearby_object_count: int,
        brightness: float,
        motion_level: float,
    ) -> str:
        parts: List[str] = []
        if face_count:
            parts.append(f"{face_count} face{'s' if face_count != 1 else ''}")
        if body_count:
            parts.append(f"{body_count} body shape{'s' if body_count != 1 else ''}")
        if person_count and not face_count and not body_count:
            parts.append(f"{person_count} person{'s' if person_count != 1 else ''}")
        if hand_count:
            parts.append(f"{hand_count} hand{'s' if hand_count != 1 else ''}")
        named = _format_object_counts([item for item in objects if item.label not in SUMMARY_EXCLUDED_OBJECT_LABELS], limit=6)
        if named:
            parts.append(", ".join(named))
        if people_count and not face_count and not body_count:
            parts.append(f"{people_count} person-shaped region{'s' if people_count != 1 else ''}")
        if nearby_object_count:
            parts.append(f"{nearby_object_count} nearby object{'s' if nearby_object_count != 1 else ''}")
        if not parts:
            parts.append("the live camera view, but no clear people or nearby objects yet")
        light = "bright" if brightness > 0.62 else "dim" if brightness < 0.28 else "moderate"
        motion = "high" if motion_level > 0.12 else "some" if motion_level > 0.035 else "low"
        strongest = next((item for item in objects if item.near), objects[0] if objects else None)
        focus = f"; closest focus is {strongest.label.replace('_', ' ')} at {strongest.zone}" if strongest is not None else ""
        return f"I see {', '.join(parts)}{focus}; light is {light}; motion is {motion}."

    def _detect_gesture(self, frame) -> Optional[Gesture]:
        if self._cv2 is None or self._hands is None:
            return None
        rgb = self._frame_to_rgb(frame)
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            return None
        hand = result.multi_hand_landmarks[0]
        name = self._classify_hand(hand.landmark)
        if name is None:
            return None
        cx = sum(point.x for point in hand.landmark) / len(hand.landmark)
        cy = sum(point.y for point in hand.landmark) / len(hand.landmark)
        msg = Gesture()
        msg.name = name
        msg.confidence = float(self.get_parameter("gesture_confidence").value)
        msg.location = Point(x=float(cx), y=float(cy), z=0.0)
        return msg

    def _classify_hand(self, landmarks: List[Any]) -> Optional[str]:
        extended = {
            "index": landmarks[8].y < landmarks[6].y,
            "middle": landmarks[12].y < landmarks[10].y,
            "ring": landmarks[16].y < landmarks[14].y,
            "pinky": landmarks[20].y < landmarks[18].y,
        }
        thumb_far = abs(landmarks[4].x - landmarks[9].x) > abs(landmarks[3].x - landmarks[9].x)
        count = sum(1 for value in extended.values() if value)
        if count == 4 and thumb_far:
            return "open_palm"
        if extended["index"] and extended["middle"] and not extended["ring"] and not extended["pinky"]:
            return "peace"
        if extended["index"] and count == 1:
            return "point"
        if count == 0 and thumb_far:
            return "thumbs_up"
        if count == 0:
            return "fist"
        return None

    def _frame_to_gray(self, frame):
        if len(frame.shape) == 2:
            return frame
        channels = frame.shape[2]
        if channels == 4:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_BGRA2GRAY)
        if self._camera_backend == "picamera2":
            return self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2GRAY)
        return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)

    def _frame_to_rgb(self, frame):
        if len(frame.shape) == 2:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_GRAY2RGB)
        channels = frame.shape[2]
        if channels == 4:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_BGRA2RGB)
        if self._camera_backend == "picamera2":
            return frame
        return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)

    def _frame_to_bgr(self, frame):
        if len(frame.shape) == 2:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_GRAY2BGR)
        channels = frame.shape[2]
        if channels == 4:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_BGRA2BGR)
        if self._camera_backend == "picamera2":
            return self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2BGR)
        return frame

    def _frame_for_preview(self, frame):
        if self._camera_backend == "picamera2" and len(frame.shape) == 3:
            return self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2BGR)
        return frame

    def _publish_faces(self, faces: List[FaceDetection]) -> None:
        msg = FaceDetectionArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        msg.faces = faces
        self._faces_pub.publish(msg)

    def _draw_preview(self, frame, faces: List[FaceDetection], gesture: Optional[Gesture], scene: Optional[VisionScene]) -> None:
        if self._cv2 is None:
            return
        frame = self._frame_for_preview(frame)
        height, width = frame.shape[:2]
        for face in faces:
            x = int(face.x * width)
            y = int(face.y * height)
            w = int(face.width * width)
            h = int(face.height * height)
            self._cv2.rectangle(frame, (x, y), (x + w, y + h), (80, 220, 120), 2)
        if gesture is not None:
            self._cv2.putText(
                frame,
                gesture.name,
                (20, 40),
                self._cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (80, 220, 120),
                2,
            )
        if scene is not None:
            for item in scene.objects:
                if item.label in {"face", "hand"}:
                    continue
                left = int(item.x * width)
                top = int(item.y * height)
                box_width = int(item.width * width)
                box_height = int(item.height * height)
                color = (220, 140, 80) if item.near else (220, 180, 80)
                self._cv2.rectangle(frame, (left, top), (left + box_width, top + box_height), color, 1)
                self._cv2.putText(frame, item.label, (left, max(14, top - 4)), self._cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            self._cv2.putText(frame, scene.summary[:80], (20, height - 20), self._cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
        self._cv2.imshow("Iris eyes", frame)
        self._cv2.waitKey(1)

    def destroy_node(self) -> bool:
        if self._capture is not None:
            self._capture.release()
        if self._picamera2 is not None:
            self._picamera2.stop()
            self._picamera2.close()
        if self._hands is not None:
            self._hands.close()
        if self._cv2 is not None and self.show_preview:
            self._cv2.destroyAllWindows()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()