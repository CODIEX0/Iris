from __future__ import annotations

import os
import platform
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path


VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
PIPER_VERSION = os.getenv("PIPER_VERSION", "2023.11.14-2")
PIPER_VOICE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx"
PIPER_VOICE_JSON = PIPER_VOICE + ".json"
MOBILENET_SSD_PROTOTXT = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt"
MOBILENET_SSD_MODEL = "https://github.com/chuanqi305/MobileNet-SSD/raw/master/mobilenet_iter_73000.caffemodel"


def main() -> int:
    model_dir = Path(os.getenv("IRIS_DESKTOP_MODEL_DIR", Path.home() / ".iris" / "models")).expanduser()
    model_dir.mkdir(parents=True, exist_ok=True)
    download_vosk(model_dir)
    download_piper(model_dir)
    download_object_detector(model_dir)
    print(f"Models are ready under {model_dir}")
    return 0


def download_vosk(model_dir: Path) -> None:
    target = model_dir / "vosk-model-small-en-us-0.15"
    if target.exists():
        return
    archive = model_dir / "vosk-model-small-en-us-0.15.zip"
    download(VOSK_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(model_dir)


def download_piper(model_dir: Path) -> None:
    piper_dir = model_dir / "piper"
    piper_dir.mkdir(parents=True, exist_ok=True)
    download_piper_binary(model_dir, piper_dir)
    voice = piper_dir / "en_US-amy-medium.onnx"
    voice_json = piper_dir / "en_US-amy-medium.onnx.json"
    if not voice.exists():
        download(PIPER_VOICE, voice)
    if not voice_json.exists():
        download(PIPER_VOICE_JSON, voice_json)


def download_piper_binary(model_dir: Path, piper_dir: Path) -> None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    executable = piper_dir / ("piper.exe" if system == "windows" else "piper")
    if executable.exists():
        return
    asset = None
    if system == "windows" and machine in {"amd64", "x86_64"}:
        asset = "piper_windows_amd64.zip"
    elif system == "linux" and machine in {"aarch64", "arm64"}:
        asset = "piper_linux_aarch64.tar.gz"
    elif system == "linux" and machine in {"x86_64", "amd64"}:
        asset = "piper_linux_x86_64.tar.gz"
    if asset is None:
        print(f"No Piper binary asset for {system}/{machine}; pyttsx3 will be used if Piper is unavailable.")
        return
    archive = model_dir / asset
    url = f"https://github.com/rhasspy/piper/releases/download/{PIPER_VERSION}/{asset}"
    try:
        download(url, archive)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(model_dir)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(model_dir)
        if not executable.exists():
            for candidate in model_dir.rglob(executable.name):
                if candidate != executable:
                    shutil.move(str(candidate), str(executable))
                    break
    except Exception as exc:
        print(f"Could not download Piper binary: {exc}")
        print("Offline TTS will fall back to pyttsx3 or console if Piper is unavailable.")


def download_object_detector(model_dir: Path) -> None:
    detector_dir = Path(os.getenv("IRIS_OBJECT_MODEL_DIR", model_dir / "object_detection")).expanduser()
    detector_dir.mkdir(parents=True, exist_ok=True)
    prototxt = detector_dir / "MobileNetSSD_deploy.prototxt"
    model = detector_dir / "MobileNetSSD_deploy.caffemodel"
    download(MOBILENET_SSD_PROTOTXT, prototxt)
    download(MOBILENET_SSD_MODEL, model)


def download(url: str, destination: Path) -> None:
    if destination.exists():
        return
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, destination)


if __name__ == "__main__":
    raise SystemExit(main())