"""Bridge between ROS 2 and pypot. Owns the Dynamixel bus."""
from __future__ import annotations

import math
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, Iterable, Optional

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
        self.declare_parameter("control_backend", "auto")
        self.declare_parameter("rest_base_url", "http://poppy.local:8080")
        self.declare_parameter("rest_timeout_sec", 1.0)
        self.declare_parameter("rest_command_duration_sec", 0.25)
        self.declare_parameter("rest_wait_for_moves", False)
        self.declare_parameter("joint_velocity_limit", 1.5)
        self.declare_parameter("joint_torque_limit_pct", 40.0)
        self.declare_parameter("compliance_on_boot", True)
        self.declare_parameter("watchdog_timeout_ms", 500)
        self.declare_parameter("publish_rate_hz", 50.0)

        self.simulate: bool = self.get_parameter("simulate").value
        self.control_backend: str = str(self.get_parameter("control_backend").value or "auto").lower()
        self.rest_base_url: str = str(self.get_parameter("rest_base_url").value or "http://poppy.local:8080")
        self.rest_timeout_sec: float = float(self.get_parameter("rest_timeout_sec").value)
        self.rest_command_duration_sec: float = float(self.get_parameter("rest_command_duration_sec").value)
        self.rest_wait_for_moves: bool = bool(self.get_parameter("rest_wait_for_moves").value)
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

        backend = getattr(self.robot, "backend", "local")
        self.get_logger().info(
            f"poppy_driver_node up ({backend.upper()}) "
            f"{len(self._joint_names)} joints; vlim={self.vel_limit} "
            f"tlim={self.torque_limit_pct}% wd={self.watchdog_ms}ms"
        )

    def _init_robot(self):
        if self.simulate or self.control_backend == "sim":
            return _FakeRobot()
        if self.control_backend == "rest":
            return self._init_rest_robot(required=True)
        if self.control_backend == "local":
            return self._init_local_robot(required=True)
        try:
            return self._init_local_robot(required=True)
        except Exception as exc:
            self.get_logger().warn(f"local Poppy backend unavailable: {exc}")
        try:
            return self._init_rest_robot(required=True)
        except Exception as exc:
            self.get_logger().warn(f"REST Poppy backend unavailable: {exc}; falling back to fake")
            return _FakeRobot()

    def _init_local_robot(self, required: bool = False):
        try:
            from poppy.creatures import PoppyHumanoid
        except ImportError as exc:
            if required:
                raise RuntimeError("poppy-humanoid is not installed") from exc
            return _FakeRobot()
        robot = PoppyHumanoid()
        try:
            robot.backend = "local"
        except Exception:
            pass
        if self.compliance_on_boot:
            for motor in robot.motors:
                motor.compliant = True
                try:
                    motor.torque_limit = self.torque_limit_pct
                except AttributeError:
                    pass
        return robot

    def _init_rest_robot(self, required: bool = False):
        try:
            robot = _RestRobot(self.rest_base_url, self.rest_timeout_sec, self.rest_wait_for_moves)
            robot.refresh(force=True)
            if self.compliance_on_boot:
                robot.configure_on_boot(self.torque_limit_pct)
            return robot
        except Exception:
            if required:
                raise
            return _FakeRobot()

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
            rest_names = []
            rest_positions_deg = []
            for name, pos_rad in zip(names, positions_rad):
                pos_rad = self._apply_trim(name, pos_rad)
                pos_deg = math.degrees(pos_rad)
                if isinstance(self.robot, _RestRobot):
                    rest_names.append(name)
                    rest_positions_deg.append(pos_deg)
                    continue
                try:
                    motor = getattr(self.robot, name)
                except AttributeError:
                    continue
                motor.compliant = False
                motor.moving_speed = min(self.vel_limit * 60.0 / (2 * math.pi), 100.0)
                motor.goal_position = pos_deg
            if rest_names:
                self.robot.goto(rest_names, rest_positions_deg, self._command_duration(point))

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
            if isinstance(self.robot, _RestRobot):
                self.robot.go_compliant()
            else:
                for m in self.robot.motors:
                    m.compliant = True

    def _command_duration(self, point) -> float:
        duration = getattr(point, "time_from_start", None)
        if duration is not None:
            seconds = float(duration.sec) + float(duration.nanosec) / 1e9
            if seconds > 0.0:
                return seconds
        return max(0.05, self.rest_command_duration_sec)

    def _publish_state(self) -> None:
        if isinstance(self.robot, _RestRobot):
            self.robot.refresh()
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
    backend = "sim"

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


class _RestMotor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.present_position = 0.0
        self.present_speed = 0.0
        self.present_load = 0.0
        self.goal_position = 0.0
        self.compliant = True
        self.torque_limit = 100.0


class _RestRobot:
    backend = "rest"

    def __init__(self, base_url: str, timeout_sec: float, wait_for_moves: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.wait_for_moves = wait_for_moves
        self._enabled_motors: set[str] = set()
        self._last_refresh = 0.0
        motor_names = self._motor_names()
        self.motors = [_RestMotor(name) for name in motor_names]
        for motor in self.motors:
            setattr(self, motor.name, motor)

    def configure_on_boot(self, torque_limit_pct: float) -> None:
        for motor in self.motors:
            self._post(f"/motors/{motor.name}/registers/compliant/value.json", True, quiet=True)
            self._post(f"/motors/{motor.name}/registers/torque_limit/value.json", float(torque_limit_pct), quiet=True)

    def goto(self, names: Iterable[str], positions_deg: Iterable[float], duration: float) -> None:
        valid_names = []
        valid_positions = []
        for name, position in zip(names, positions_deg):
            if not hasattr(self, name):
                continue
            valid_names.append(name)
            valid_positions.append(float(position))
            motor = getattr(self, name)
            motor.goal_position = float(position)
            motor.present_position = float(position)
        if not valid_names:
            return
        for name in valid_names:
            self._enable_motor(name)
        self._post(
            "/motors/goto.json",
            {
                "motors": valid_names,
                "positions": valid_positions,
                "duration": f"{max(0.05, float(duration)):.3f}",
                "wait": "true" if self.wait_for_moves else "false",
            },
        )

    def go_compliant(self) -> None:
        for motor in self.motors:
            self._post(f"/motors/{motor.name}/registers/compliant/value.json", True, quiet=True)
        self._enabled_motors.clear()

    def refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_refresh < 0.2:
            return
        self._last_refresh = now
        self._update_register("present_position")
        self._update_register("present_speed")
        self._update_register("present_load")

    def _motor_names(self) -> list[str]:
        payload = self._get("/motors/list.json")
        names = payload.get("motors", [])
        if not isinstance(names, list) or not names:
            raise RuntimeError("Poppy REST API did not return any motors")
        return [str(name) for name in names]

    def _enable_motor(self, name: str) -> None:
        if name in self._enabled_motors:
            return
        self._post(f"/motors/{name}/registers/compliant/value.json", False)
        self._enabled_motors.add(name)

    def _update_register(self, register: str) -> None:
        try:
            payload = self._get(f"/motors/registers/{register}/list.json")
        except Exception:
            return
        values = payload.get(register, {})
        if not isinstance(values, dict):
            return
        attr = register
        for name, value in values.items():
            if hasattr(self, name):
                try:
                    setattr(getattr(self, name), attr, float(value))
                except (TypeError, ValueError):
                    pass

    def _get(self, path: str) -> dict:
        request = urllib.request.Request(self._url(path), headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, path: str, payload, quiet: bool = False) -> Optional[dict]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url(path),
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except (urllib.error.URLError, TimeoutError):
            if quiet:
                return None
            raise

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"


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