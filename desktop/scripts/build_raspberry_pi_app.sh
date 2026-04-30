#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCH="$(uname -m)"

case "$ARCH" in
  aarch64|arm64|armv7l|armv6l) ;;
  *)
    if [ "${IRIS_ALLOW_NON_PI_BUILD:-0}" != "1" ]; then
      echo "This script must be run on the Raspberry Pi that will use the app."
      echo "Current machine architecture is $ARCH, so it would not create a Pi app."
      echo "Set IRIS_ALLOW_NON_PI_BUILD=1 only if you intentionally want a non-Pi Linux build."
      exit 1
    fi
    ;;
esac

cd "$ROOT"

RELEASE_ROOT="$ROOT/release/iris-raspberry-pi"
MODEL_DIR="$RELEASE_ROOT/models"
PYINSTALLER_WORK="$ROOT/build/pyinstaller-raspberry-pi"
PYINSTALLER_SPEC="$ROOT/build/pyinstaller-spec"

mkdir -p "$RELEASE_ROOT" "$MODEL_DIR" "$PYINSTALLER_WORK" "$PYINSTALLER_SPEC"

sudo apt update
sudo apt install -y \
  alsa-utils \
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
python -m pip install --upgrade pip pyinstaller
python -m pip install -r desktop/requirements-pi-os.txt
python -m pip install -e desktop

export IRIS_DESKTOP_MODEL_DIR="$MODEL_DIR"
export IRIS_OBJECT_MODEL_DIR="$MODEL_DIR/object_detection"
python desktop/scripts/download_desktop_models.py

python -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --console \
  --name IrisDesktop \
  --paths desktop \
  --hidden-import pyttsx3.drivers \
  --hidden-import pyttsx3.drivers.espeak \
  --hidden-import sounddevice \
  --hidden-import vosk \
  --hidden-import websockets \
  --hidden-import pygame \
  --hidden-import cv2 \
  --distpath "$RELEASE_ROOT" \
  --workpath "$PYINSTALLER_WORK" \
  --specpath "$PYINSTALLER_SPEC" \
  desktop/iris_desktop/__main__.py

cat > "$RELEASE_ROOT/.env.local.example" <<'EOF'
DEEPGRAM_API_KEY=your-deepgram-key
GEMINI_API_KEY=your-gemini-key
# Optional secondary cloud fallback:
# GROQ_API_KEY=your-groq-key
EOF

cat > "$RELEASE_ROOT/run_iris_online.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IRIS_DESKTOP_MODEL_DIR="$DIR/models"
export IRIS_OBJECT_MODEL_DIR="$DIR/models/object_detection"
exec "$DIR/IrisDesktop/IrisDesktop" --mode auto --camera-backend auto --object-detection on --object-confidence 0.35 "$@"
EOF

cat > "$RELEASE_ROOT/run_iris_offline.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IRIS_DESKTOP_MODEL_DIR="$DIR/models"
export IRIS_OBJECT_MODEL_DIR="$DIR/models/object_detection"
exec "$DIR/IrisDesktop/IrisDesktop" --mode offline --camera-backend auto --object-detection on --object-confidence 0.35 "$@"
EOF

chmod +x "$RELEASE_ROOT/run_iris_online.sh" "$RELEASE_ROOT/run_iris_offline.sh"

cat > "$RELEASE_ROOT/README.txt" <<'EOF'
Iris Desktop for Raspberry Pi OS

1. Copy .env.local.example to .env.local.
2. Paste DEEPGRAM_API_KEY for online voice mode.
3. Run ./run_iris_online.sh for Deepgram online mode.
4. Run ./run_iris_offline.sh for offline local mode.

Object recognition uses the bundled free open-source MobileNet SSD Caffe model
from https://github.com/chuanqi305/MobileNet-SSD under the MIT license, loaded
locally with OpenCV DNN. Iris can name the VOC object classes that model knows,
including person, bottle, chair, car, bicycle, bus, cat, dog, sofa, train, and
TV monitor.

Build this package on the Raspberry Pi that will run it. Windows .exe files do
not run on Raspberry Pi OS.
EOF

tar -C "$ROOT/release" -czf "$ROOT/release/iris-raspberry-pi.tar.gz" iris-raspberry-pi

echo
echo "Raspberry Pi Iris app built at: $RELEASE_ROOT"
echo "Archive: $ROOT/release/iris-raspberry-pi.tar.gz"
echo "Run: $RELEASE_ROOT/run_iris_online.sh"