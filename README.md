# Iris

A ROS 2 stack that turns a **Poppy Humanoid** into an interactive AI
companion for STEM outreach. Iris talks to kids, tracks their faces and
hand gestures, shows an animated face on a touchscreen, balances itself,
and remembers new gestures you teach it by moving its arms.

## What's in the box

| Capability | ROS 2 package | Tools |
|---|---|---|
| Brain (LLM) | `iris_brain` | Groq (default), Ollama, Gemini |
| Eyes | `iris_eyes` | OpenCV face detection + optional MediaPipe hand gestures |
| Ears | `iris_ears` | Vosk microphone STT, keyboard fallback |
| Mouth | `iris_mouth` | Piper or pyttsx3 TTS, console fallback, visemes |
| Animated face | `iris_face` | Pygame touchscreen face + touch zones |
| Balance | `iris_balance` | MPU6050 IMU + PID |
| Motion | `iris_motion` | `pypot` ↔ ROS 2 bridge, move recorder |
| Conversation FSM | `iris_orchestrator` | lightweight ROS behavior coordinator |
| Bring-up | `iris_bringup` | launch files, configs, systemd |

Every hardware-facing node has a simulation or fallback path, so you can
bring the whole graph up before connecting motors, camera, microphone, or
speaker hardware.

## Hardware targets

- **Raspberry Pi 5** (8 GB recommended) — best performance.
- **Raspberry Pi 4** (4 GB+) — works with smaller models.
- 64-bit Ubuntu 22.04 arm64 with ROS 2 Humble is the supported image.
    32-bit Pi OS can run some Python fallbacks, but ROS 2, Piper, and
    MediaPipe support are much less predictable.
- Pi Camera Module 3 or USB webcam
- USB microphone + speaker
- 7" 800×480 touchscreen
- MPU6050 IMU (I2C)
- Poppy Humanoid with Dynamixel motors

## Quick start

```bash
# 1. Flash Ubuntu 22.04 Server arm64, boot, create user.
# 2. Install ROS 2 Humble (official debs)
sudo apt install software-properties-common curl
sudo add-apt-repository universe
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
    | sudo tee /etc/apt/sources.list.d/ros2.list
sudo apt update && sudo apt install -y ros-humble-ros-base python3-colcon-common-extensions

# 3. Workspace
git clone -b claude/poppy-robot-ai-interface-O5MdU <this-repo> ~/iris_ws
cd ~/iris_ws
bash src/iris_bringup/scripts/install_deps.sh

# Reboot or log out/in after install_deps.sh so i2c/dialout/audio/video
# group changes and Pi firmware config are active.
sudo reboot

cd ~/iris_ws
bash src/iris_bringup/scripts/download_models.sh
cp src/iris_bringup/config/iris.pi.example.yaml iris.pi.yaml
bash src/iris_bringup/scripts/check_pi.sh

# 4. Environment
export GROQ_API_KEY=...   # free key at console.groq.com

# 5. Build
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash

# 6. Run in safe simulation mode first
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml \
    simulate:=true speech_backend:=keyboard tts_backend:=console

# 7. Hardware sanity, then full robot
ros2 launch iris_bringup hardware_only.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml simulate:=false
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml simulate:=false

# 8. Autostart (optional)
sudo cp src/iris_bringup/systemd/iris@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iris@$USER
```

Before the hardware run, edit `~/iris_ws/iris.pi.yaml` for that Pi:
camera index, fullscreen/headless face mode, microphone device, Piper path,
IMU address, motor safety limits, and whether each hardware node should
start in simulation. Keep motor velocity and torque conservative until the
robot is physically supported.

## Useful launch modes

```bash
# Perception UI only: camera/keyboard/TTS/face, no robot motors.
ros2 launch iris_bringup perception.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml \
    simulate:=true speech_backend:=keyboard tts_backend:=console

# Motor + IMU/balance only.
ros2 launch iris_bringup hardware_only.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml simulate:=true

# Full stack with a local Ollama model instead of Groq.
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml simulate:=true
ros2 param set /brain_node backend ollama
```

## Runtime map

- `/speech/transcript` feeds recognized text into `iris_brain`.
- `/brain/response` is spoken by `iris_mouth` and mirrored in logs.
- `/emotion/current` and `/mouth/viseme` drive the animated face.
- `/vision/faces`, `/gesture/detected`, and `/touch/event` give the
    orchestrator social context.
- `/motion/play_gesture` and `/motion/play` play recorded Poppy motions.
- `/joint_commands`, `/joint_states`, `/joint_trim`, and `/safety/estop`
    connect motion and balance.

## Model and hardware notes

- `download_models.sh` installs a small Vosk English model, the Piper
    `en_US-amy-medium` voice, and a Piper executable when one is available
    for the Pi architecture.
- `check_pi.sh` verifies ROS 2, colcon, I2C, user groups, camera, audio,
    Dynamixel serial adapters, models, and key Python imports before you
    trust the robot on hardware.
- Set `GROQ_API_KEY`, `GEMINI_API_KEY`, or run Ollama locally before using
    cloud/local LLM backends.
- Keep `simulate:=true` until the robot is physically supported and the
    Dynamixel bus, IMU, e-stop behavior, and joint directions have been
    checked.
- If `mediapipe`, Piper, camera, or audio packages are unavailable on a
    specific Pi image, Iris still runs with OpenCV face detection, keyboard
    speech input, console/pyttsx3 speech output, and simulation mode.

## License

MIT — free for educational use.