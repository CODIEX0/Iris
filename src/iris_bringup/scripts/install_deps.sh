#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y \
  alsa-utils \
  curl \
  espeak-ng \
  i2c-tools \
  portaudio19-dev \
  python3-opencv \
  python3-pip \
  python3-pygame \
  python3-smbus \
  unzip

if command -v rosdep >/dev/null 2>&1; then
  rosdep update || true
  rosdep install --from-paths src --ignore-src -r -y
fi

python3 -m pip install --user --upgrade pip
python3 -m pip install --user httpx smbus2 sounddevice vosk pyttsx3
python3 -m pip install --user mediapipe || true

echo "Optional: install Piper from https://github.com/rhasspy/piper for higher-quality speech."