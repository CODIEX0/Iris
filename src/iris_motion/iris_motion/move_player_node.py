"""Play back recorded moves as JointTrajectory streams."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import rclpy
from ament_index_python.packages import get_package_share_directory
from builtin_interfaces.msg import Duration
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from iris_msgs.action import PlayMoveSequence
from iris_msgs.srv import PlayGesture


def _duration_from_seconds(seconds: float) -> Duration:
    d = Duration()
    d.sec = int(seconds)
    d.nanosec = int((seconds - int(seconds)) * 1e9)
    return d


class MovePlayerNode(Node):
    def __init__(self) -> None:
        super().__init__("move_player_node")

        self.declare_parameter("moves_dir", "")
        default_moves = os.path.join(get_package_share_directory("iris_motion"), "moves")
        self.moves_dir = Path(self.get_parameter("moves_dir").value or default_moves)

        self._cmd_pub = self.create_publisher(JointTrajectory, "/joint_commands", 10)
        self._active_lock = threading.Lock()

        cb = ReentrantCallbackGroup()
        self._action_server = ActionServer(
            self,
            PlayMoveSequence,
            "/motion/play",
            execute_callback=self._execute_play,
            goal_callback=lambda _: GoalResponse.ACCEPT,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb,
        )
        self.create_service(PlayGesture, "/motion/play_gesture", self._on_play_gesture, callback_group=cb)

        self.get_logger().info(f"move_player_node ready, moves_dir={self.moves_dir}")

    def _load_move(self, name: str) -> Optional[dict]:
        path = self.moves_dir / f"{name}.json"
        if not path.exists():
            self.get_logger().error(f"move not found: {path}")
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as e:
            self.get_logger().error(f"bad move json {path}: {e}")
            return None

    def _publish_point(self, names, positions) -> None:
        msg = JointTrajectory()
        msg.joint_names = list(names)
        msg.header.stamp = self.get_clock().now().to_msg()
        pt = JointTrajectoryPoint()
        pt.positions = [float(p) for p in positions]
        pt.time_from_start = _duration_from_seconds(0.0)
        msg.points.append(pt)
        self._cmd_pub.publish(msg)

    def _play_move(
        self,
        move: dict,
        speed_scale: float,
        should_cancel: Optional[Callable[[], bool]] = None,
        feedback_cb: Optional[Callable[[float], None]] = None,
    ) -> tuple[bool, float]:
        speed_scale = max(0.1, min(speed_scale, 4.0))
        names = list(move.get("names", []))
        times = [float(t) / speed_scale for t in move.get("times", [])]
        positions = move.get("positions", [])
        if not names or not times or len(times) != len(positions):
            self.get_logger().error("bad move format: names, times, and positions must be present and aligned")
            return False, 0.0

        total = times[-1] if times else 0.0
        start = time.monotonic()
        for target_t, row in zip(times, positions):
            while True:
                if should_cancel is not None and should_cancel():
                    return False, time.monotonic() - start
                remaining = target_t - (time.monotonic() - start)
                if remaining <= 0.0:
                    break
                time.sleep(min(remaining, 0.02))
            self._publish_point(names, row)
            if feedback_cb is not None:
                feedback_cb(min(1.0, target_t / max(total, 1e-3)))
        return True, total

    def _execute_play(self, goal_handle):
        goal = goal_handle.request
        move = self._load_move(goal.move_name)
        result = PlayMoveSequence.Result()
        if move is None:
            goal_handle.abort()
            result.success = False
            return result

        feedback = PlayMoveSequence.Feedback()

        def publish_feedback(progress: float) -> None:
            feedback.progress = progress
            goal_handle.publish_feedback(feedback)

        with self._active_lock:
            success, _ = self._play_move(
                move,
                goal.speed_scale or 1.0,
                should_cancel=lambda: goal_handle.is_cancel_requested,
                feedback_cb=publish_feedback,
            )

        if not success:
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
            else:
                goal_handle.abort()
            result.success = False
            return result

        goal_handle.succeed()
        result.success = True
        return result

    def _on_play_gesture(self, request: PlayGesture.Request, response: PlayGesture.Response):
        move = self._load_move(request.name)
        if move is None:
            response.success = False
            response.message = f"unknown gesture '{request.name}'"
            return response
        with self._active_lock:
            success, _ = self._play_move(move, request.speed_scale or 1.0)
        if not success:
            response.success = False
            response.message = f"failed to play {request.name}"
            return response
        response.success = True
        response.message = f"playing {request.name}"
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MovePlayerNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()