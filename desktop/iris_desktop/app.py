from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import threading
import time
from pathlib import Path

from iris_desktop.brain import OfflineBrain
from iris_desktop.deepgram_agent import DeepgramAgent
from iris_desktop.face import FaceWindow
from iris_desktop.types import Reply, Touch
from iris_desktop.vision import CameraTracker
from iris_desktop.voice import OfflineRecognizer, SpeechOutput


PROMPT = (
    "You are Iris, a friendly humanoid robot for kids and STEM demos. "
    "Keep replies short, spoken, warm, and practical. You have OpenCV camera "
    "vision that can track faces, notice profile faces, upper bodies, full "
    "body shapes, eyes, smiles, hands, motion, lighting, and nearby object-sized "
    "regions when the camera is enabled. When the local MobileNet SSD model is "
    "installed, you can name common objects like person, bottle, chair, car, dog, "
    "cat, bicycle, bus, and TV. Do not claim to identify who someone is. If asked to "
    "move, describe the intended gesture in one sentence."
)


def load_env_files() -> None:
    root = Path(__file__).resolve().parents[2]
    for path in (root / ".env.local", root / ".env", root / "desktop" / ".env.local", root / "desktop" / ".env"):
        if path.exists():
            load_env_file(path)


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    load_env_files()
    args = build_parser().parse_args(argv)
    model_dir = Path(args.model_dir).expanduser()
    face = FaceWindow(args.width, args.height, args.fullscreen)
    camera = CameraTracker(
        args.camera_index,
        args.camera_width,
        args.camera_height,
        args.no_camera,
        args.camera_backend,
        object_detection=args.object_detection,
        object_model_dir=args.object_model_dir,
        object_confidence=args.object_confidence,
    )

    try:
        if should_use_deepgram(args):
            print("Iris desktop: online Deepgram Agent mode")
            return run_online(args, face, camera)
        print("Iris desktop: offline local mode")
        return run_offline(args, model_dir, face, camera)
    except KeyboardInterrupt:
        return 0
    finally:
        camera.close()
        face.close()


def build_parser() -> argparse.ArgumentParser:
    model_dir = Path(os.getenv("IRIS_DESKTOP_MODEL_DIR", Path.home() / ".iris" / "models"))
    piper_name = "piper.exe" if sys.platform == "win32" else "piper"
    parser = argparse.ArgumentParser(description="Run Iris voice, mic, camera, and face without ROS.")
    parser.add_argument("--mode", choices=["auto", "online", "offline"], default=os.getenv("IRIS_DESKTOP_MODE", "auto"))
    parser.add_argument("--model-dir", default=str(model_dir))
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=480)
    parser.add_argument("--camera-backend", choices=["auto", "opencv", "picamera2"], default=os.getenv("IRIS_CAMERA_BACKEND", "auto"))
    parser.add_argument("--object-detection", choices=["auto", "on", "off"], default=os.getenv("IRIS_OBJECT_DETECTION", "auto"))
    parser.add_argument("--object-model-dir", default=os.getenv("IRIS_OBJECT_MODEL_DIR", str(model_dir / "object_detection")))
    parser.add_argument("--object-confidence", type=float, default=float(os.getenv("IRIS_OBJECT_CONFIDENCE", "0.45")))
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--stt-backend", choices=["auto", "vosk", "keyboard"], default="auto")
    parser.add_argument("--tts-backend", choices=["auto", "piper", "pyttsx3", "console"], default="auto")
    parser.add_argument("--offline-llm", choices=["auto", "ollama", "none"], default="auto")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--ollama-model", default="phi3:mini")
    parser.add_argument("--vosk-model", default=str(model_dir / "vosk-model-small-en-us-0.15"))
    parser.add_argument("--piper-executable", default=str(model_dir / "piper" / piper_name))
    parser.add_argument("--piper-voice", default=str(model_dir / "piper" / "en_US-amy-medium.onnx"))
    parser.add_argument("--deepgram-url", default=os.getenv("DEEPGRAM_AGENT_URL", "wss://agent.deepgram.com/v1/agent/converse"))
    parser.add_argument("--deepgram-listen-model", default=os.getenv("DEEPGRAM_LISTEN_MODEL", "nova-3"))
    parser.add_argument("--deepgram-speak-model", default=os.getenv("DEEPGRAM_SPEAK_MODEL", "aura-2-thalia-en"))
    parser.add_argument("--deepgram-think-provider", default=os.getenv("DEEPGRAM_THINK_PROVIDER", "open_ai"))
    parser.add_argument("--deepgram-think-model", default=os.getenv("DEEPGRAM_THINK_MODEL", "gpt-4o-mini"))
    return parser


def should_use_deepgram(args: argparse.Namespace) -> bool:
    if args.mode == "offline":
        return False
    api_key = os.getenv("DEEPGRAM_API_KEY", "")
    if not api_key:
        if args.mode == "online":
            print("DEEPGRAM_API_KEY is not set; falling back to offline mode.")
        return False
    if args.mode == "online":
        return True
    return internet_available("agent.deepgram.com", 443)


def internet_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def run_online(args: argparse.Namespace, face: FaceWindow, camera: CameraTracker) -> int:
    agent = DeepgramAgent(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        prompt=PROMPT,
        url=args.deepgram_url,
        listen_model=args.deepgram_listen_model,
        speak_model=args.deepgram_speak_model,
        think_provider=args.deepgram_think_provider,
        think_model=args.deepgram_think_model,
        on_text=lambda role, text: on_deepgram_text(face, camera, role, text),
        on_viseme=face.set_viseme,
    )

    def run_agent() -> None:
        try:
            asyncio.run(agent.run())
        except BaseException as exc:
            agent.error = exc

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()
    try:
        while True:
            face.set_eye_target(camera.poll())
            face.step()
            if agent.error is not None:
                print(f"Deepgram mode stopped: {agent.error}")
                print("Switching to offline mode.")
                model_dir = Path(args.model_dir).expanduser()
                return run_offline(args, model_dir, face, camera)
    finally:
        agent.stop_from_thread()
        thread.join(timeout=2.0)


def on_deepgram_text(face: FaceWindow, camera: CameraTracker, role: str, text: str) -> None:
    print(f"Deepgram {role}: {text}")
    lowered = text.lower()
    if role == "status" and "startedspeaking" in lowered:
        face.set_state("listening")
    elif role == "status" and "thinking" in lowered:
        face.set_state("thinking")
    elif role == "user":
        if is_vision_question(text):
            print(f"Iris vision: {camera.describe_scene()}")
        face.set_state("thinking")
        face.set_emotion("thinking")
    elif role in {"assistant", "agent"}:
        face.set_state("speaking")
        face.set_emotion("happy")


def run_offline(args: argparse.Namespace, model_dir: Path, face: FaceWindow, camera: CameraTracker) -> int:
    recognizer = OfflineRecognizer(Path(args.vosk_model), backend=args.stt_backend, device="", on_status=lambda status: on_voice_status(face, status))
    input_backend = recognizer.start()
    speaker = SpeechOutput(args.tts_backend, Path(args.piper_executable), Path(args.piper_voice))
    brain_backend = "none" if args.offline_llm == "none" else args.offline_llm
    brain = OfflineBrain(brain_backend, args.ollama_url, args.ollama_model)

    print(f"Mic/STT backend: {input_backend}")
    print(f"TTS backend: {speaker.backend}")
    print("Say something, or type into the terminal if keyboard mode is active.")
    face.set_state("listening")

    def handle_touch(touch: Touch) -> None:
        reply = Reply(f"You touched my {touch.zone}. That was a {touch.action}.", "happy")
        speak_reply(face, speaker, reply)

    face.on_touch = handle_touch
    try:
        while True:
            face.set_eye_target(camera.poll())
            text = recognizer.poll()
            if text:
                print(f"You: {text}")
                face.set_emotion("thinking")
                reply = Reply(camera.describe_scene(), "curious") if is_vision_question(text) else brain.reply(text)
                speak_reply(face, speaker, reply)
            face.step()
            time.sleep(0.005)
    finally:
        recognizer.stop()


def speak_reply(face: FaceWindow, speaker: SpeechOutput, reply: Reply) -> None:
    face.set_emotion(reply.emotion)
    face.set_state("speaking")
    speaker.speak_async(reply.text, reply.emotion, face.set_viseme, lambda: face.set_state("listening"))


def on_voice_status(face: FaceWindow, status: str) -> None:
    if status in {"listening", "hearing"}:
        face.set_state("listening")
    elif status == "heard":
        face.set_state("thinking")


def is_vision_question(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "what can you see",
            "what do you see",
            "can you see",
            "look around",
            "look at the room",
            "what is in front",
            "who is in front",
            "is anyone there",
            "do you see me",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())