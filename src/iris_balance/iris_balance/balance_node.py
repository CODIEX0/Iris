"""Standing balance controller."""
from __future__ import annotations

import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu

from iris_balance.pid import PID
from iris_msgs.msg import JointTrim


class BalanceNode(Node):
    def __init__(self) -> None:
        super().__init__("balance_node")
        self.declare_parameter("enabled", True)
        self.declare_parameter("pitch_kp", 0.6)
        self.declare_parameter("pitch_ki", 0.05)
        self.declare_parameter("pitch_kd", 0.08)
        self.declare_parameter("roll_kp", 0.4)
        self.declare_parameter("roll_ki", 0.03)
        self.declare_parameter("roll_kd", 0.05)
        self.declare_parameter("max_trim_rad", 0.25)
        self.declare_parameter("publish_rate_hz", 50.0)

        self.enabled = bool(self.get_parameter("enabled").value)
        limit = float(self.get_parameter("max_trim_rad").value)
        self.pitch_pid = PID(
            self.get_parameter("pitch_kp").value,
            self.get_parameter("pitch_ki").value,
            self.get_parameter("pitch_kd").value,
            output_limit=limit,
        )
        self.roll_pid = PID(
            self.get_parameter("roll_kp").value,
            self.get_parameter("roll_ki").value,
            self.get_parameter("roll_kd").value,
            output_limit=limit,
        )

        self._latest_imu: Imu | None = None
        self.create_subscription(Imu, "/imu/data", self._on_imu, 50)
        self.pub_trim = self.create_publisher(JointTrim, "/joint_trim", 10)

        rate = float(self.get_parameter("publish_rate_hz").value)
        self.create_timer(1.0 / rate, self._step)
        self.get_logger().info(f"balance_node up @ {rate} Hz enabled={self.enabled}")

    def _on_imu(self, msg: Imu) -> None:
        self._latest_imu = msg

    def _step(self) -> None:
        if not self.enabled or self._latest_imu is None:
            return
        q = self._latest_imu.orientation
        sinr_cosp = 2.0 * (q.w * q.x + q.y * q.z)
        cosr_cosp = 1.0 - 2.0 * (q.x * q.x + q.y * q.y)
        roll = math.atan2(sinr_cosp, cosr_cosp)
        sinp = 2.0 * (q.w * q.y - q.z * q.x)
        pitch = math.copysign(math.pi / 2, sinp) if abs(sinp) >= 1 else math.asin(sinp)

        pitch_trim = self.pitch_pid.step(-pitch)
        roll_trim = self.roll_pid.step(-roll)

        out = JointTrim()
        out.joint_names = [
            "l_ankle_y", "r_ankle_y",
            "l_hip_x", "r_hip_x",
        ]
        out.trim_offsets = [pitch_trim, pitch_trim, roll_trim, roll_trim]
        self.pub_trim.publish(out)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BalanceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()