"""MPU6050 reader. Publishes sensor_msgs/Imu at `rate_hz`."""
from __future__ import annotations

import math
import time

import rclpy
from geometry_msgs.msg import Quaternion, Vector3
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import Bool

from iris_balance.complementary_filter import ComplementaryFilter


def _euler_to_quaternion(roll: float, pitch: float, yaw: float) -> Quaternion:
    cr = math.cos(roll * 0.5); sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5); sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5); sy = math.sin(yaw * 0.5)
    q = Quaternion()
    q.w = cr * cp * cy + sr * sp * sy
    q.x = sr * cp * cy - cr * sp * sy
    q.y = cr * sp * cy + sr * cp * sy
    q.z = cr * cp * sy - sr * sp * cy
    return q


class MPU6050:
    PWR_MGMT_1 = 0x6B
    ACCEL_XOUT_H = 0x3B
    ACCEL_SCALE = 16384.0
    GYRO_SCALE = 131.0
    G = 9.80665

    def __init__(self, bus_num: int = 1, address: int = 0x68) -> None:
        import smbus2
        self.bus = smbus2.SMBus(bus_num)
        self.address = address
        self.bus.write_byte_data(self.address, self.PWR_MGMT_1, 0)
        time.sleep(0.05)

    def _read_word(self, reg: int) -> int:
        high = self.bus.read_byte_data(self.address, reg)
        low = self.bus.read_byte_data(self.address, reg + 1)
        val = (high << 8) | low
        if val >= 0x8000:
            val -= 0x10000
        return val

    def read(self):
        ax = self._read_word(self.ACCEL_XOUT_H) / self.ACCEL_SCALE * self.G
        ay = self._read_word(self.ACCEL_XOUT_H + 2) / self.ACCEL_SCALE * self.G
        az = self._read_word(self.ACCEL_XOUT_H + 4) / self.ACCEL_SCALE * self.G
        gx = math.radians(self._read_word(self.ACCEL_XOUT_H + 8) / self.GYRO_SCALE)
        gy = math.radians(self._read_word(self.ACCEL_XOUT_H + 10) / self.GYRO_SCALE)
        gz = math.radians(self._read_word(self.ACCEL_XOUT_H + 12) / self.GYRO_SCALE)
        return ax, ay, az, gx, gy, gz


class _FakeMPU:
    def read(self):
        return 0.0, 0.0, 9.80665, 0.0, 0.0, 0.0


class ImuNode(Node):
    def __init__(self) -> None:
        super().__init__("imu_node")
        self.declare_parameter("i2c_bus", 1)
        self.declare_parameter("i2c_address", 0x68)
        self.declare_parameter("rate_hz", 100.0)
        self.declare_parameter("alpha", 0.98)
        self.declare_parameter("simulate", False)
        self.declare_parameter("estop_tilt_deg", 35.0)

        simulate = bool(self.get_parameter("simulate").value)
        self.estop_tilt = math.radians(float(self.get_parameter("estop_tilt_deg").value))

        if simulate:
            self.sensor = _FakeMPU()
            self.get_logger().warn("IMU simulated (upright, still)")
        else:
            try:
                self.sensor = MPU6050(
                    bus_num=int(self.get_parameter("i2c_bus").value),
                    address=int(self.get_parameter("i2c_address").value),
                )
            except Exception as e:
                self.get_logger().error(f"IMU init failed ({e}); falling back to simulated")
                self.sensor = _FakeMPU()

        self.filter = ComplementaryFilter(alpha=float(self.get_parameter("alpha").value))
        self.pub_imu = self.create_publisher(Imu, "/imu/data", 50)
        self.pub_estop = self.create_publisher(Bool, "/safety/estop", 10)

        self._last_t = time.monotonic()
        self._estop_latched = False
        rate_hz = float(self.get_parameter("rate_hz").value)
        self.create_timer(1.0 / rate_hz, self._tick)
        self.get_logger().info(f"imu_node up @ {rate_hz} Hz, estop_tilt={math.degrees(self.estop_tilt):.1f}°")

    def _tick(self) -> None:
        ax, ay, az, gx, gy, gz = self.sensor.read()
        now = time.monotonic()
        dt = max(1e-3, now - self._last_t)
        self._last_t = now
        att = self.filter.update(ax, ay, az, gx, gy, dt)

        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "imu_link"
        msg.orientation = _euler_to_quaternion(att.roll, att.pitch, 0.0)
        msg.angular_velocity = Vector3(x=float(gx), y=float(gy), z=float(gz))
        msg.linear_acceleration = Vector3(x=float(ax), y=float(ay), z=float(az))
        self.pub_imu.publish(msg)

        tilt = max(abs(att.roll), abs(att.pitch))
        estop = tilt > self.estop_tilt
        if estop != self._estop_latched:
            self._estop_latched = estop
            self.pub_estop.publish(Bool(data=estop))
            if estop:
                self.get_logger().warn(f"TILT {math.degrees(tilt):.1f}° → e-stop")
            else:
                self.get_logger().info("tilt ok → releasing e-stop")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ImuNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()