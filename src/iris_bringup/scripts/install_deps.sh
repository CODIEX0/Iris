#!/usr/bin/env bash
set -euo pipefail

ROS_DISTRO="${ROS_DISTRO:-humble}"
APT_ROS_PREFIX="ros-${ROS_DISTRO}"
USER_NAME="${SUDO_USER:-$USER}"

if ! grep -qi "raspberry pi\|aarch64\|arm" /proc/cpuinfo 2>/dev/null && [ "${IRIS_ALLOW_NON_PI:-0}" != "1" ]; then
  echo "This script is intended for Raspberry Pi class hardware."
  echo "Set IRIS_ALLOW_NON_PI=1 to run it on another Linux machine."
fi

sudo apt update
sudo apt install -y \
  alsa-utils \
  curl \
  espeak-ng \
  i2c-tools \
  portaudio19-dev \
  python3-colcon-common-extensions \
  python3-dev \
  python3-opencv \
  python3-pip \
  python3-pygame \
  python3-rosdep \
  python3-setuptools \
  python3-smbus \
  python3-venv \
  v4l-utils \
  unzip

for optional_package in libatlas-base-dev libcamera-apps libcamera-tools; do
  sudo apt install -y "$optional_package" || true
done

if [ -d "/opt/ros/${ROS_DISTRO}" ]; then
  sudo apt install -y \
    "${APT_ROS_PREFIX}-geometry-msgs" \
    "${APT_ROS_PREFIX}-launch" \
    "${APT_ROS_PREFIX}-launch-ros" \
    "${APT_ROS_PREFIX}-ros-base" \
    "${APT_ROS_PREFIX}-ros2launch" \
    "${APT_ROS_PREFIX}-sensor-msgs" \
    "${APT_ROS_PREFIX}-std-msgs" \
    "${APT_ROS_PREFIX}-trajectory-msgs"
fi

for group in i2c dialout audio video input; do
  if getent group "$group" >/dev/null 2>&1; then
    sudo usermod -aG "$group" "$USER_NAME"
  fi
done

for config in /boot/firmware/config.txt /boot/config.txt; do
  if [ -f "$config" ] && ! grep -q "^dtparam=i2c_arm=on" "$config"; then
    echo "Enabling I2C in $config"
    echo "dtparam=i2c_arm=on" | sudo tee -a "$config" >/dev/null
  fi
done

if command -v rosdep >/dev/null 2>&1; then
  sudo rosdep init 2>/dev/null || true
  rosdep update || true
  rosdep install --from-paths src --ignore-src -r -y
fi

python3 -m pip install --user --upgrade pip
python3 -m pip install --user httpx smbus2 sounddevice vosk pyttsx3
python3 -m pip install --user mediapipe || true
python3 -m pip install --user pypot || true

echo "Dependency install complete. Reboot or log out/in so group changes and I2C config take effect."
echo "Run: bash src/iris_bringup/scripts/download_models.sh"
echo "Then run: bash src/iris_bringup/scripts/check_pi.sh"