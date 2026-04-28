#!/usr/bin/env bash
set -euo pipefail

WARNINGS=0
ERRORS=0
ROS_DISTRO="${ROS_DISTRO:-humble}"
MODEL_DIR="${IRIS_MODELS_DIR:-$HOME/iris_models}"

info() { printf '[ OK ] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '[FAIL] %s\n' "$1"; ERRORS=$((ERRORS + 1)); }

have_command() { command -v "$1" >/dev/null 2>&1; }
in_group() { id -nG "$USER" | tr ' ' '\n' | grep -qx "$1"; }

echo "Iris Raspberry Pi preflight"
echo "==========================="

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) info "64-bit ARM OS detected ($ARCH)" ;;
  armv7l|armhf) warn "32-bit ARM detected; ROS 2/Piper/MediaPipe support is limited. Use Ubuntu 22.04 arm64 when possible." ;;
  *) warn "Non-Pi architecture detected ($ARCH); hardware checks may not reflect the target Pi." ;;
esac

if [ -r /proc/device-tree/model ]; then
  info "Hardware: $(tr -d '\0' </proc/device-tree/model)"
else
  warn "Could not read Raspberry Pi model from /proc/device-tree/model"
fi

if [ -d "/opt/ros/${ROS_DISTRO}" ]; then
  # shellcheck disable=SC1090
  source "/opt/ros/${ROS_DISTRO}/setup.bash"
  info "ROS 2 ${ROS_DISTRO} found"
else
  fail "ROS 2 ${ROS_DISTRO} not found at /opt/ros/${ROS_DISTRO}"
fi

have_command colcon && info "colcon found" || fail "colcon not found; install python3-colcon-common-extensions"
have_command ros2 && info "ros2 CLI found" || fail "ros2 CLI not found; source ROS or install ros-${ROS_DISTRO}-ros-base"

if [ -e /dev/i2c-1 ]; then
  info "I2C bus /dev/i2c-1 present"
else
  fail "I2C bus /dev/i2c-1 missing; enable I2C and reboot"
fi

for group in i2c dialout audio video input; do
  if getent group "$group" >/dev/null 2>&1; then
    in_group "$group" && info "User $USER is in group $group" || warn "User $USER is not in group $group"
  fi
done

if compgen -G "/dev/video*" >/dev/null; then
  info "Video device present: $(ls /dev/video* | tr '\n' ' ')"
elif have_command libcamera-hello; then
  warn "No /dev/video* device found; Pi camera may need libcamera/V4L2 compatibility setup"
else
  warn "No camera device detected"
fi

if have_command arecord && arecord -l >/dev/null 2>&1; then
  info "Microphone/input audio device detected"
else
  warn "No microphone found by arecord"
fi

if have_command aplay && aplay -l >/dev/null 2>&1; then
  info "Speaker/output audio device detected"
else
  warn "No speaker found by aplay"
fi

if compgen -G "/dev/ttyUSB*" >/dev/null || compgen -G "/dev/ttyACM*" >/dev/null; then
  info "Possible Dynamixel serial adapter present"
else
  warn "No /dev/ttyUSB* or /dev/ttyACM* adapter detected for Poppy motors"
fi

if [ -d "$MODEL_DIR/vosk-model-small-en-us-0.15" ]; then
  info "Vosk model installed"
else
  warn "Vosk model missing under $MODEL_DIR; run download_models.sh"
fi

if [ -x "$MODEL_DIR/piper/piper" ] && [ -f "$MODEL_DIR/piper/en_US-amy-medium.onnx" ]; then
  info "Piper executable and voice installed"
else
  warn "Piper executable or voice missing under $MODEL_DIR; TTS will fall back to pyttsx3/console"
fi

python3 - <<'PY' || fail "Python runtime import check failed"
import importlib

required = ["rclpy", "httpx", "smbus2"]
optional = ["cv2", "pygame", "sounddevice", "vosk", "pyttsx3", "mediapipe"]

for name in required:
    importlib.import_module(name)
    print(f"[ OK ] Python import {name}")

for name in optional:
    try:
        importlib.import_module(name)
        print(f"[ OK ] Python import {name}")
    except Exception as exc:
        print(f"[WARN] Optional Python import {name} failed: {exc}")
PY

if have_command ros2; then
  if ros2 pkg prefix iris_bringup >/dev/null 2>&1; then
    info "Iris packages are built and sourced"
  else
    warn "Iris packages are not visible to ros2 yet; run colcon build and source install/setup.bash"
  fi
fi

echo
echo "Preflight complete: $ERRORS error(s), $WARNINGS warning(s)."
if [ "$ERRORS" -gt 0 ]; then
  exit 1
fi