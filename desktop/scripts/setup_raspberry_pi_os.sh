#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

sudo apt update
sudo apt install -y \
  alsa-utils \
  curl \
  espeak-ng \
  libasound2-dev \
  portaudio19-dev \
  python3-dev \
  python3-opencv \
  python3-pip \
  python3-pygame \
  python3-venv \
  unzip \
  v4l-utils

for optional_package in libcamera-apps libcamera-tools python3-picamera2; do
  sudo apt install -y "$optional_package" || true
done

python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r desktop/requirements-pi-os.txt
python -m pip install -e desktop
python desktop/scripts/download_desktop_models.py

echo
echo "Iris desktop is ready."
echo "Offline test: source .venv/bin/activate && iris-desktop --mode offline"
echo "Online test: export DEEPGRAM_API_KEY=your-key && iris-desktop --mode auto"