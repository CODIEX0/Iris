"""Camera perception node for faces and simple hand gestures."""
from __future__ import annotations

from typing import Any, List, Optional

import rclpy
from geometry_msgs.msg import Point
from rclpy.node import Node

from iris_msgs.msg import FaceDetection, FaceDetectionArray, Gesture


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


class VisionNode(Node):
    def __init__(self) -> None:
        super().__init__("vision_node")
        self.declare_parameter("camera_index", 0)
        self.declare_parameter("frame_width", 640)
        self.declare_parameter("frame_height", 480)
        self.declare_parameter("rate_hz", 15.0)
        self.declare_parameter("simulate", False)
        self.declare_parameter("show_preview", False)
        self.declare_parameter("min_face_size_px", 60)
        self.declare_parameter("gesture_confidence", 0.82)

        self.simulate = bool(self.get_parameter("simulate").value)
        self.show_preview = bool(self.get_parameter("show_preview").value)
        self._cv2 = _try_import_cv2()
        self._mp = _try_import_mediapipe()
        self._hands = self._create_hands()
        self._face_detector = self._create_face_detector()
        self._capture = self._open_camera()

        self._faces_pub = self.create_publisher(FaceDetectionArray, "/vision/faces", 10)
        self._gesture_pub = self.create_publisher(Gesture, "/gesture/detected", 10)

        rate_hz = float(self.get_parameter("rate_hz").value)
        self.create_timer(1.0 / rate_hz, self._tick)
        mode = "simulated" if self.simulate or self._capture is None else "camera"
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
        cascade_path = self._cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        detector = self._cv2.CascadeClassifier(cascade_path)
        if detector.empty():
            self.get_logger().warn("OpenCV face cascade not found; face detection disabled")
            return None
        return detector

    def _open_camera(self):
        if self.simulate or self._cv2 is None:
            return None
        index = int(self.get_parameter("camera_index").value)
        capture = self._cv2.VideoCapture(index)
        if not capture.isOpened():
            self.get_logger().warn(f"camera {index} unavailable; publishing simulated faces")
            self.simulate = True
            return None
        capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, int(self.get_parameter("frame_width").value))
        capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, int(self.get_parameter("frame_height").value))
        return capture

    def _tick(self) -> None:
        frame = self._read_frame()
        if frame is None:
            self._publish_simulated()
            return

        faces = self._detect_faces(frame)
        self._publish_faces(faces)
        gesture = self._detect_gesture(frame)
        if gesture is not None:
            self._gesture_pub.publish(gesture)
        if self.show_preview:
            self._draw_preview(frame, faces, gesture)

    def _read_frame(self):
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

    def _detect_faces(self, frame) -> List[FaceDetection]:
        if self._cv2 is None or self._face_detector is None:
            return []
        height, width = frame.shape[:2]
        gray = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
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

    def _detect_gesture(self, frame) -> Optional[Gesture]:
        if self._cv2 is None or self._hands is None:
            return None
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
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

    def _publish_faces(self, faces: List[FaceDetection]) -> None:
        msg = FaceDetectionArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        msg.faces = faces
        self._faces_pub.publish(msg)

    def _draw_preview(self, frame, faces: List[FaceDetection], gesture: Optional[Gesture]) -> None:
        if self._cv2 is None:
            return
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
        self._cv2.imshow("Iris eyes", frame)
        self._cv2.waitKey(1)

    def destroy_node(self) -> bool:
        if self._capture is not None:
            self._capture.release()
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