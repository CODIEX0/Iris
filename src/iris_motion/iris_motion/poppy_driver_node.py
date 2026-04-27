"""Bridge between ROS 2 and pypot. Owns the Dynamixel bus."""
from __future__ import annotations

import math
import threading
import time
from typing import Dict

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool
from trajectory_msgs.msg import JointTrajectory

from iris_msgs.msg import JointTrim


class PoppyDriverNode(Node):
    def __init__(self) -> None:
        super().__init__("poppy_driver_node")

        self.declare_parameter("simulate", False)
        self.declare_parameter("joint_velocity_limit", 1.5)
        self.declare_parameter("joint_torque_limit_pct", 40.0)
        self.declare_parameter("compliance_on_boot", True)
        self.declare_parameter("watchdog_timeout_ms", 500)
        self.declare_parameter("publish_rate_hz", 50.0)

        self.simulate: bool = self.get_parameter("simulate").value
        self.vel_limit: float = float(self.get_parameter("joint_velocity_limit").value)
        self.torque_limit_pct: float = float(self.get_parameter("joint_torque_limit_pct").value)
        self.compliance_on_boot: bool = bool(self.get_parameter("compliance_on_boot").value)
        self.watchdog_ms: int = int(self.get_parameter("watchdog_timeout_ms").value)
        self.publish_rate_hz: float = float(self.get_parameter("publish_rate_hz").value)

        self._trim: Dict[str, float] = {}
        self._last_cmd_time: float = time.monotonic()
        self._estop: bool = False
        self._lock = threading.RLock()

        self.robot = self._init_robot()
        self._joint_names = [m.name for m in self.robot.motors]

        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(JointTrajectory, "/joint_commands", self._on_cmd, qos)
        self.create_subscription(JointTrim, "/joint_trim", self._on_trim, qos)
        self.create_subscription(Bool, "/safety/estop", self._on_estop, qos)
        self._state_pub = self.create_publisher(JointState, "/joint_states", qos)

        self.create_timer(1.0 / self.publish_rate_hz, self._publish_state)
        self.create_timer(0.1, self._watchdog)

        self.get_logger().info(
            f"poppy_driver_node up ({'SIM' if self.simulate else 'REAL'}) "
            f"{len(self._joint_names)} joints; vlim={self.vel_limit} "
            f"tlim={self.torque_limit_pct}% wd={self.watchdog_ms}ms"
        )

    def _init_robot(self):
        if self.simulate:
            return _FakeRobot()
        try:
            from poppy.creatures import PoppyHumanoid
        except ImportError:
            self.get_logger().warn("poppy-humanoid not installed — falling back to fake")
            return _FakeRobot()
        robot = PoppyHumanoid()
        if self.compliance_on_boot:
            for m in robot.motors:
                m.compliant = True
                try:
                    m.torque_limit = self.torque_limit_pct
                except AttributeError:
                    pass
        return robot

    def _on_cmd(self, msg: JointTrajectory) -> None:
        if self._estop:
            return
        if not msg.points:
            return
        point = msg.points[-1]
        names = list(msg.joint_names)
        positions_rad = list(point.positions)
        with self._lock:
            self._last_cmd_time = time.monotonic()
            for name, pos_rad in zip(names, positions_rad):
                pos_rad = self._apply_trim(name, pos_rad)
                try:
                    motor = getattr(self.robot, name)
                except AttributeError:
                    continue
                motor.compliant = False
                motor.moving_speed = min(self.vel_limit * 60.0 / (2 * math.pi), 100.0)
                motor.goal_position = math.degrees(pos_rad)

    def _apply_trim(self, name: str, pos_rad: float) -> float:
        return pos_rad + self._trim.get(name, 0.0)

    def _on_trim(self, msg: JointTrim) -> None:
        with self._lock:
            self._trim = dict(zip(msg.joint_names, msg.trim_offsets))

    def _on_estop(self, msg: Bool) -> None:
        if msg.data and not self._estop:
            self.get_logger().warn("E-stop asserted — going compliant")
            self._go_compliant()
        self._estop = bool(msg.data)

    def _watchdog(self) -> None:
        if self._estop:
            return
        if (time.monotonic() - self._last_cmd_time) * 1000.0 > self.watchdog_ms:
            self._go_compliant()

    def _go_compliant(self) -> None:
        with self._lock:
            for m in self.robot.motors:
                m.compliant = True

    def _publish_state(self) -> None:
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(self._joint_names)
        msg.position = [math.radians(getattr(self.robot, n).present_position) for n in self._joint_names]
        msg.velocity = [math.radians(getattr(self.robot, n).present_speed) for n in self._joint_names]
        msg.effort = [float(getattr(self.robot, n).present_load) for n in self._joint_names]
        self._state_pub.publish(msg)


class _FakeMotor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.present_position = 0.0
        self.present_speed = 0.0
        self.present_load = 0.0
        self.goal_position = 0.0
        self.moving_speed = 0.0
        self.compliant = True
        self.torque_limit = 100.0

    def __setattr__(self, key, value):
        if key == "goal_position":
            object.__setattr__(self, "present_position", float(value))
        object.__setattr__(self, key, value)


class _FakeRobot:
    _JOINT_NAMES = [
        "l_hip_x", "l_hip_z", "l_hip_y", "l_knee_y", "l_ankle_y",
        "r_hip_x", "r_hip_z", "r_hip_y", "r_knee_y", "r_ankle_y",
        "abs_y", "abs_x", "abs_z", "bust_y", "bust_x",
        "head_z", "head_y",
        "l_shoulder_y", "l_shoulder_x", "l_arm_z", "l_elbow_y",
        "r_shoulder_y", "r_shoulder_x", "r_arm_z", "r_elbow_y",
    ]

    def __init__(self) -> None:
        self.motors = [_FakeMotor(n) for n in self._JOINT_NAMES]
        for m in self.motors:
            setattr(self, m.name, m)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PoppyDriverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._go_compliant()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()