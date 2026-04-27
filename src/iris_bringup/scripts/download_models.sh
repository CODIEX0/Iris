#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${IRIS_MODELS_DIR:-$HOME/iris_models}"
VOSK_ZIP="$MODEL_DIR/vosk-model-small-en-us-0.15.zip"
VOSK_DIR="$MODEL_DIR/vosk-model-small-en-us-0.15"
PIPER_DIR="$MODEL_DIR/piper"

mkdir -p "$MODEL_DIR" "$PIPER_DIR"

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

echo "Models installed under $MODEL_DIR"