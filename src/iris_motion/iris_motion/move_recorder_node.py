"""Teach-by-demonstration: record /joint_states to a JSON file."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import List, Optional

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from sensor_msgs.msg import JointState

from iris_msgs.srv import RecordGesture


class MoveRecorderNode(Node):
    def __init__(self) -> None:
        super().__init__("move_recorder_node")

        self.declare_parameter("moves_dir", "")
        default_moves = os.path.join(get_package_share_directory("iris_motion"), "moves")
        self.moves_dir = Path(self.get_parameter("moves_dir").value or default_moves)
        self.moves_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._recording: bool = False
        self._move_name: Optional[str] = None
        self._sample_rate: float = 10.0
        self._last_sample_t: float = 0.0
        self._t0: float = 0.0
        self._names: List[str] = []
        self._times: List[float] = []
        self._positions: List[List[float]] = []

        self.create_subscription(JointState, "/joint_states", self._on_state, 10)
        self.create_service(RecordGesture, "/motion/record", self._on_record)

        self.get_logger().info(f"move_recorder_node ready, moves_dir={self.moves_dir}")

    def _on_record(self, req: RecordGesture.Request, resp: RecordGesture.Response):
        with self._lock:
            if req.start:
                if self._recording:
                    resp.success = False
                    resp.samples_captured = len(self._times)
                    return resp
                self._move_name = req.name or f"move_{int(time.time())}"
                self._sample_rate = req.sample_rate if req.sample_rate > 0 else 10.0
                self._recording = True
                self._t0 = time.monotonic()
                self._last_sample_t = 0.0
                self._names = []
                self._times = []
                self._positions = []
                self.get_logger().info(f"recording → {self._move_name} @ {self._sample_rate} Hz")
                resp.success = True
                resp.samples_captured = 0
                return resp

            if not self._recording:
                resp.success = False
                resp.samples_captured = 0
                return resp
            self._recording = False
            count = self._save()
            resp.success = count > 0
            resp.samples_captured = count
            return resp

    def _on_state(self, msg: JointState) -> None:
        with self._lock:
            if not self._recording:
                return
            now = time.monotonic() - self._t0
            if now - self._last_sample_t < 1.0 / self._sample_rate:
                return
            self._last_sample_t = now
            if not self._names:
                self._names = list(msg.name)
            self._times.append(now)
            by_name = dict(zip(msg.name, msg.position))
            self._positions.append([float(by_name.get(n, 0.0)) for n in self._names])

    def _save(self) -> int:
        if not self._move_name or not self._times:
            return 0
        out = {
            "names": self._names,
            "times": self._times,
            "positions": self._positions,
        }
        path = self.moves_dir / f"{self._move_name}.json"
        path.write_text(json.dumps(out, indent=2))
        self.get_logger().info(f"saved {path} ({len(self._times)} samples)")
        return len(self._times)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MoveRecorderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()