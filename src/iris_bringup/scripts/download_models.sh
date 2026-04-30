#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${IRIS_MODELS_DIR:-$HOME/iris_models}"
VOSK_ZIP="$MODEL_DIR/vosk-model-small-en-us-0.15.zip"
VOSK_DIR="$MODEL_DIR/vosk-model-small-en-us-0.15"
PIPER_DIR="$MODEL_DIR/piper"
PIPER_VERSION="${PIPER_VERSION:-2023.11.14-2}"
OBJECT_DIR="${IRIS_OBJECT_MODEL_DIR:-$MODEL_DIR/object_detection}"
MOBILENET_SSD_SOURCE="https://github.com/chuanqi305/MobileNet-SSD"

mkdir -p "$MODEL_DIR" "$PIPER_DIR" "$OBJECT_DIR"

ARCH="$(uname -m)"
if [ ! -x "$PIPER_DIR/piper" ]; then
  case "$ARCH" in
    aarch64|arm64)
      PIPER_TARBALL="$MODEL_DIR/piper_linux_aarch64.tar.gz"
      curl -L "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_aarch64.tar.gz" -o "$PIPER_TARBALL"
      tar -xzf "$PIPER_TARBALL" -C "$MODEL_DIR"
      ;;
    x86_64|amd64)
      PIPER_TARBALL="$MODEL_DIR/piper_linux_x86_64.tar.gz"
      curl -L "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" -o "$PIPER_TARBALL"
      tar -xzf "$PIPER_TARBALL" -C "$MODEL_DIR"
      ;;
    *)
      echo "No bundled Piper binary for architecture $ARCH; install Piper manually or use tts_backend:=pyttsx3/console."
      ;;
  esac
fi

if [ ! -d "$VOSK_DIR" ]; then
  curl -L "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -o "$VOSK_ZIP"
  unzip -q "$VOSK_ZIP" -d "$MODEL_DIR"
fi

if [ ! -f "$PIPER_DIR/en_US-amy-medium.onnx" ]; then
  curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx" \
    -o "$PIPER_DIR/en_US-amy-medium.onnx"
  curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json" \
    -o "$PIPER_DIR/en_US-amy-medium.onnx.json"
fi

if [ ! -f "$OBJECT_DIR/MobileNetSSD_deploy.prototxt" ]; then
  curl -L "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt" \
    -o "$OBJECT_DIR/MobileNetSSD_deploy.prototxt"
fi

if [ ! -f "$OBJECT_DIR/MobileNetSSD_deploy.caffemodel" ]; then
  curl -L "https://github.com/chuanqi305/MobileNet-SSD/raw/master/mobilenet_iter_73000.caffemodel" \
    -o "$OBJECT_DIR/MobileNetSSD_deploy.caffemodel"
fi

cat > "$OBJECT_DIR/OPEN_SOURCE_MODELS.txt" <<EOF
Iris object recognition model
=============================

Model: MobileNet SSD Caffe detector trained for VOC object classes.
Source: $MOBILENET_SSD_SOURCE
License: MIT
Runtime: OpenCV DNN, distributed through the open-source OpenCV project.

Files used by Iris:
- MobileNetSSD_deploy.prototxt
- MobileNetSSD_deploy.caffemodel

Recognized classes include person, bottle, chair, car, bicycle, bus, cat, dog, sofa, train, and TV monitor.
EOF

echo "Models installed under $MODEL_DIR"
echo "Object recognition model ready: MobileNet SSD (MIT, open source)"