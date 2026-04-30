# Iris

A ROS 2 stack that turns a **Poppy Humanoid** into an interactive AI
companion for STEM outreach. Iris talks to kids, tracks their faces and
hand gestures, shows an animated face on a touchscreen, balances itself,
and remembers new gestures you teach it by moving its arms.

## What's in the box

| Capability | ROS 2 package | Tools |
|---|---|---|
| Brain (LLM) | `iris_brain` | Gemini (default), Groq fallback, Ollama local fallback |
| Eyes | `iris_eyes` | OpenCV face detection + optional MediaPipe hand gestures |
| Ears | `iris_ears` / `iris-desktop` | Vosk offline STT, keyboard fallback, Deepgram Agent online |
| Mouth | `iris_mouth` / `iris-desktop` | Piper or pyttsx3 offline TTS, Deepgram Agent online, visemes |
| Animated face | `iris_face` | Pygame touchscreen face + touch zones |
| Balance | `iris_balance` | MPU6050 IMU + PID |
| Motion | `iris_motion` | `pypot` ↔ ROS 2 bridge, move recorder |
| Conversation FSM | `iris_orchestrator` | lightweight ROS behavior coordinator |
| Bring-up | `iris_bringup` | launch files, configs, systemd |

Every hardware-facing node has a simulation or fallback path, so you can
bring the whole graph up before connecting motors, camera, microphone, or
speaker hardware. The voice, mic, camera, and animated face can also run
without ROS through the `iris-desktop` runtime on Windows and Raspberry Pi
Desktop OS.

## Run on the Iris robot

Start with the desktop runtime when you want to test Iris's face, voice,
microphone, camera, object recognition, and Deepgram interaction on Raspberry
Pi Desktop OS. Use the ROS 2 runtime when you are ready to control the Poppy
body, gestures, balance, and robot hardware topics.

### Option 1: PC controls Poppy through REST

Use this setup when you do not have much access to the robot's onboard
computer. Iris runs on your PC, and the school robot only needs its existing
Poppy/pypot REST API running on the same network.

```text
Your Ubuntu 22.04 PC running Iris ROS 2
        -> Wi-Fi/Ethernet
        -> Poppy REST API on the robot controller
        -> Dynamixel motors
```

Use Ubuntu 22.04 with ROS 2 Humble on the PC for the full system. Native
Ubuntu is best for the face window, microphone, speaker, and webcam. WSL2 can
work for keyboard/console control tests, but camera, audio, and GUI access are
less predictable.

First, get the robot's REST URL from the school. It is often one of these:

```bash
http://poppy.local:8080
http://<robot-ip-address>:8080
```

Test the REST API from your PC before launching Iris:

```bash
curl http://poppy.local:8080/motors/list.json
curl http://poppy.local:8080/motors/registers/present_position/list.json
```

If `poppy.local` does not resolve, use the robot's IP address instead.

Set up Iris on the PC:

```bash
mkdir -p ~/iris_ws/src
cd ~/iris_ws/src
git clone <your-github-repo-url> Iris

cd ~/iris_ws
source /opt/ros/humble/setup.bash
IRIS_ALLOW_NON_PI=1 bash src/Iris/src/iris_bringup/scripts/install_deps.sh
bash src/Iris/src/iris_bringup/scripts/download_models.sh
cp src/Iris/src/iris_bringup/config/iris.remote_rest.example.yaml iris.remote.yaml
nano .env.local
```

Put your cloud brain key in `~/iris_ws/.env.local`:

```bash
GEMINI_API_KEY=your-gemini-key
# Optional secondary cloud fallback:
# GROQ_API_KEY=your-groq-key
```

Build the workspace:

```bash
cd ~/iris_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Start with keyboard input and console speech so the first test only checks the
brain, ROS graph, and REST motor path:

```bash
ros2 launch iris_bringup remote_rest.launch.py \
    params_file:=$HOME/iris_ws/iris.remote.yaml \
    poppy_rest_url:=http://poppy.local:8080 \
    speech_backend:=keyboard \
    tts_backend:=console
```

When that works, switch to microphone, speaker, face, and camera on the PC:

```bash
ros2 launch iris_bringup remote_rest.launch.py \
    params_file:=$HOME/iris_ws/iris.remote.yaml \
    poppy_rest_url:=http://poppy.local:8080 \
    speech_backend:=auto \
    tts_backend:=auto
```

Keep the robot supported and ask the school to stay near the robot for the
first movement test. Try safe commands first:

```text
Iris, wave.
Iris, nod your head.
Iris, relax your body.
```

Useful checks from another terminal:

```bash
source /opt/ros/humble/setup.bash
source ~/iris_ws/install/setup.bash
ros2 topic echo /body/command
ros2 topic echo /joint_states
```

### Pi Desktop face, voice, and vision

Use this path on normal Raspberry Pi Desktop OS. It does not require Ubuntu,
ROS 2, or colcon.

```bash
# 1. Get the project onto the Pi.
git clone <your-github-repo-url> ~/Iris
cd ~/Iris

# 2. Install Python dependencies and download local models.
bash desktop/scripts/setup_raspberry_pi_os.sh

# 3. Add online API keys.
nano .env.local
```

Put this in `.env.local`:

```bash
# Used by iris-desktop online voice mode.
DEEPGRAM_API_KEY=your-deepgram-key

# Used by the ROS brain. Gemini is tried before Groq and Ollama.
GEMINI_API_KEY=your-gemini-key
# Optional secondary cloud fallback:
# GROQ_API_KEY=your-groq-key
```

Run Iris with face, camera, mic, speaker, Deepgram, and named object detection:

```bash
cd ~/Iris
source .venv/bin/activate
iris-desktop --mode auto --camera-backend auto --object-detection on --fullscreen
```

Run fully offline, using local open-source speech and vision tools:

```bash
cd ~/Iris
source .venv/bin/activate
iris-desktop --mode offline --camera-backend auto --object-detection on --fullscreen
```

Say or type prompts such as:

```text
Iris, what can you see?
Iris, look around.
Iris, can you see me?
```

Iris can track faces and, when the MobileNet SSD model is installed, name
common objects such as person, bottle, chair, car, dog, cat, bicycle, bus,
potted plant, sofa, train, and TV. The setup script downloads the object model
under `~/.iris/models/object_detection`.

### Full ROS robot body runtime

Use this path on Ubuntu 22.04 64-bit with ROS 2 Humble when you are ready to
run the Poppy body, gestures, IMU, balance, speech, face, and camera nodes.

```bash
# 1. Create the ROS workspace.
mkdir -p ~/iris_ws/src
cd ~/iris_ws/src
git clone <your-github-repo-url> Iris

# 2. Install OS, Python, camera, audio, ROS, and hardware dependencies.
cd ~/iris_ws
bash src/Iris/src/iris_bringup/scripts/install_deps.sh
sudo reboot
```

After reboot:

```bash
cd ~/iris_ws
source /opt/ros/humble/setup.bash

# 3. Download local Vosk, Piper, and MobileNet SSD object-recognition models.
bash src/Iris/src/iris_bringup/scripts/download_models.sh

# 4. Copy and edit the Pi hardware config.
cp src/Iris/src/iris_bringup/config/iris.pi.example.yaml iris.pi.yaml
nano iris.pi.yaml

# 5. Add Gemini as Iris's default brain key. Groq can be added as fallback.
nano .env.local
```

Put this in `~/iris_ws/.env.local`:

```bash
GEMINI_API_KEY=your-gemini-key
# Optional secondary cloud fallback:
# GROQ_API_KEY=your-groq-key
```

Continue setup:

```bash
# 6. Check Pi camera/audio/I2C/groups/models before trusting hardware.
bash src/Iris/src/iris_bringup/scripts/check_pi.sh

# 7. Build the ROS workspace.
colcon build --symlink-install
source install/setup.bash
```

Run the full graph safely in simulation first:

```bash
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml \
    simulate:=true speech_backend:=keyboard tts_backend:=console
```

Run the real robot body through Poppy's REST API:

```bash
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml \
    simulate:=false \
    motion_backend:=rest \
    poppy_rest_url:=http://poppy.local:8080
```

Run the real robot body through local `pypot` instead:

```bash
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml \
    simulate:=false \
    motion_backend:=local
```

Keep the robot physically supported during first hardware tests. Start with low
torque and conservative velocity settings in `iris.pi.yaml`, verify the e-stop,
then try simple body commands:

```text
Iris, wave.
Iris, nod your head.
Iris, give me a thumbs up.
Iris, relax your body.
```

Useful ROS checks while the robot is running:

```bash
ros2 topic echo /vision/scene
ros2 topic echo /vision/faces
ros2 topic echo /gesture/detected
ros2 topic echo /body/command
ros2 topic echo /joint_states
```

## Desktop voice and face testing

Use this mode for real-world microphone, speaker, camera, Deepgram, and
face testing on Windows or normal Raspberry Pi Desktop OS. It does not
require Ubuntu, ROS 2, or colcon.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\setup_windows.ps1

# Offline: Vosk STT + Piper/pyttsx3 TTS + local fallback brain.
.\.venv\Scripts\iris-desktop.exe --mode offline

# Online when internet is available: Deepgram Voice Agent API.
$env:DEEPGRAM_API_KEY="your-deepgram-key"
.\.venv\Scripts\iris-desktop.exe --mode auto
```

### Raspberry Pi Desktop OS

```bash
bash desktop/scripts/setup_raspberry_pi_os.sh
source .venv/bin/activate

# Offline: Vosk STT + Piper/pyttsx3 TTS + local fallback brain.
iris-desktop --mode offline

# Online when internet is available: Deepgram Voice Agent API.
export DEEPGRAM_API_KEY=your-deepgram-key
iris-desktop --mode auto
```

`--mode auto` uses Deepgram Agent only when `DEEPGRAM_API_KEY` is set and
`agent.deepgram.com` is reachable. Otherwise Iris falls back to local,
open-source resources: Vosk for STT, Piper or pyttsx3 for TTS, OpenCV for
face tracking, Pygame for the face, and Ollama if it is running locally.
The downloaded desktop models live under `~/.iris/models` by default.

Object recognition is local and free/open source on every supported runtime.
The setup scripts download the MIT-licensed MobileNet SSD Caffe detector from
https://github.com/chuanqi305/MobileNet-SSD and load it with OpenCV DNN. Iris can
name the VOC object classes that model knows, including person, bottle, chair,
car, bicycle, bus, cat, dog, sofa, train, and TV monitor. The object model files
are stored under `~/.iris/models/object_detection` for the desktop app and under
`~/iris_models/object_detection` for ROS/Pi launches. A local
`OPEN_SOURCE_MODELS.txt` notice is written beside the model files.

To install or refresh the object model for each system:

```powershell
# Windows desktop app
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\setup_windows.ps1
```

```bash
# Raspberry Pi Desktop OS app
bash desktop/scripts/setup_raspberry_pi_os.sh

# ROS robot runtime on Ubuntu/Raspberry Pi
bash src/iris_bringup/scripts/download_models.sh
```

### Standalone desktop app builds

You can build a standalone app folder for Windows and a separate app folder for
Raspberry Pi OS. The app folders include the executable, run scripts, example
env file, and local models. They do not include `.env.local`, so paste API keys
after copying the release to another machine.

Build the Windows PC app from this repository on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build_windows_exe.ps1
```

The output is:

```text
release\iris-windows\run_iris_online.bat
release\iris-windows\run_iris_offline.bat
release\iris-windows\IrisDesktop\IrisDesktop.exe
release\iris-windows.zip
```

Build the Raspberry Pi OS app on the Raspberry Pi itself:

```bash
bash desktop/scripts/build_raspberry_pi_app.sh
```

The output is:

```text
release/iris-raspberry-pi/run_iris_online.sh
release/iris-raspberry-pi/run_iris_offline.sh
release/iris-raspberry-pi/IrisDesktop/IrisDesktop
release/iris-raspberry-pi.tar.gz
```

Windows `.exe` files do not run on Raspberry Pi OS. The Pi release must be
built on the Pi so PyInstaller creates the correct ARM Linux executable.

Useful desktop flags:

```bash
iris-desktop --mode offline --stt-backend keyboard
iris-desktop --mode offline --tts-backend pyttsx3
iris-desktop --mode offline --offline-llm ollama --ollama-model phi3:mini
iris-desktop --mode auto --fullscreen
iris-desktop --mode auto --camera-backend opencv     # Windows/USB webcam
iris-desktop --mode auto --camera-backend picamera2  # Raspberry Pi Camera Module
iris-desktop --mode auto --object-detection on       # Require MobileNet SSD object names
iris-desktop --mode auto --object-confidence 0.35    # More sensitive object naming
iris-desktop --mode auto --deepgram-think-provider open_ai --deepgram-think-model gpt-4o-mini
```

Camera tracking is enabled by default. On Windows, `iris-desktop` uses
OpenCV with the default webcam. On Raspberry Pi Desktop OS, `--camera-backend
auto` tries Picamera2/libcamera first for Pi Camera modules, then OpenCV for
USB webcams. Use `--camera-index 1` when the camera is not the first device,
or `--no-camera` to run the face without vision. The desktop camera layer also
keeps an OpenCV scene summary for faces, profile faces, upper/full body shapes,
eyes, smiles, hands, motion, lighting, and nearby object-sized contours. When
the MobileNet SSD model is installed, Iris can also name common objects such as
person, bottle, chair, car, dog, cat, bicycle, bus, potted plant, sofa, train,
and TV. The setup scripts download that model into `~/.iris/models/object_detection`
for desktop mode and `~/iris_models/object_detection` for ROS mode.

## Hardware targets

- **Raspberry Pi 5** (8 GB recommended) — best performance.
- **Raspberry Pi 4** (4 GB+) — works with smaller models.
- For the full ROS robot stack: 64-bit Ubuntu 22.04 arm64 with ROS 2
    Humble is the simplest supported image.
- For voice, mic, camera, and face testing only: Windows and Raspberry Pi
    Desktop OS are supported through `iris-desktop`.
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
# Gemini is the default brain. Groq is the secondary cloud fallback.
nano .env.local
```

Add these values to `.env.local`:

```bash
GEMINI_API_KEY=your-gemini-key
# Optional secondary cloud fallback:
# GROQ_API_KEY=your-groq-key
```

```bash
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

# If your Poppy hardware is exposed through pypot's REST server instead of
# a local Dynamixel bus, use the REST motion backend.
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml simulate:=false \
    motion_backend:=rest poppy_rest_url:=http://poppy.local:8080

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

# Full stack with a local Ollama model instead of Gemini/Groq.
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml simulate:=true
ros2 param set /brain_node backend ollama

# Full voice + body control through Poppy's REST API.
ros2 launch iris_bringup full.launch.py \
    params_file:=$HOME/iris_ws/iris.pi.yaml simulate:=false \
    motion_backend:=rest poppy_rest_url:=http://poppy.local:8080
```

## Voice body commands

Iris recognizes a small safe command set before sending the text to the LLM.
The brain publishes `/body/command`, the orchestrator calls
`/motion/play_gesture`, and the motion driver moves either through local pypot
or pypot's REST API.

Try phrases like:

```text
Iris, wave.
Poppy, nod your head.
Give me a thumbs up.
Relax your body.
Stop moving.
```

Available built-in gestures are `wave`, `nod`, `thumbs_up`, and `idle`. Add new
body skills by dropping a matching JSON move into `src/iris_motion/moves` and
adding a phrase in `iris_brain.body_commands`.

For REST-backed Poppy hardware, Iris uses the documented pypot endpoints:
`GET /motors/list.json`, `GET /motors/registers/<register>/list.json`,
`POST /motors/<motor>/registers/compliant/value.json`, and
`POST /motors/goto.json`.

## Runtime map

- `/speech/transcript` feeds recognized text into `iris_brain`.
- `/body/command` carries voice body intents from `iris_brain` to
    `iris_orchestrator`.
- `/brain/response` is spoken by `iris_mouth` and mirrored in logs.
- `/emotion/current` and `/mouth/viseme` drive the animated face.
- `/vision/faces`, `/vision/scene`, `/gesture/detected`, and `/touch/event`
    give the orchestrator social and environment context. `/vision/scene`
    includes faces, body regions, hands, named MobileNet SSD objects when the
    model is installed, nearby object-sized contours, brightness, motion level,
    edge density, and a short summary.
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
- Set `GEMINI_API_KEY` in `.env.local` for the default brain. If Gemini is not
    available, Iris tries `GROQ_API_KEY` next, then local Ollama.
- Keep `simulate:=true` until the robot is physically supported and the
    Dynamixel bus, IMU, e-stop behavior, and joint directions have been
    checked.
- If `mediapipe`, Piper, camera, or audio packages are unavailable on a
    specific Pi image, Iris still runs with OpenCV face detection, keyboard
    speech input, console/pyttsx3 speech output, and simulation mode.

## License

MIT — free for educational use.