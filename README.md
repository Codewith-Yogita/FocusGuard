# FocusGuard 🛡️

**FocusGuard** is a high-performance, intelligent desktop productivity, distraction-management, and biometric security system for Windows. It monitors active applications, extracts browser URLs, enforces user-defined focus policies, gates daemon monitoring behind **face-based recognition login**, and uses **Qwen 2.5-VL** visual AI to intelligently classify desktop activity in real time.

---

## Architecture Overview

FocusGuard operates on a hybrid, two-tier architecture:

```
+-----------------------------------------------------------------------------------+
|                                    FOCUSGUARD                                     |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +-------------------------------+             +-------------------------------+  |
|  |     FocusGuard Daemon         | <---------> |   Vision & Face Auth Bridge   |  |
|  |          (C++ 17)             |    HTTP     |           (Python)            |  |
|  +-------------------------------+    JSON     +-------------------------------+  |
|    - Startup Biometric Auth Gate    (127.0.0.1:  - /face/enroll & /face/status    |
|    - Win32 Dark Lock Screen Modal     8765)      - /face/authenticate & /presence |
|    - Presence Auto-Lock (60s)                    - OpenCV YuNet (sub-10ms detect) |
|    - Windows Session Lock Detection              - OpenCV SFace (128-d embedding) |
|    - SHA-256 Protected Fallback PIN              - Windows DPAPI Encrypted Store  |
|    - Multi-Browser UI Automation                 - Anti-Spoofing Liveness Defense |
|    - Policy Engine (ALLOW/BLOCK)                 - DirectX Duplication (dxcam)    |
|    - Non-Blocking Enforcement                    - Qwen 2.5-VL Activity Vision    |
+-----------------------------------------------------------------------------------+
```

### 1. C++ Core Daemon (`focusguard_monitor`)
* **Startup Biometric Login Gate**: Blocks monitoring, activity tracking, and policy enforcement on launch until the enrolled user verifies their face or enters a valid fallback PIN.
* **Win32 Lock Screen Dialog**: Custom dark-themed modal window with live status indicators, retry triggers, and password-masked PIN entry.
* **Presence Auto-Lock & Workstation Lock**: Periodically probes `/face/presence` every 5 seconds. If the user is absent for longer than the auto-lock timeout (default 60s) or Windows workstation is locked/screensaver activated, FocusGuard automatically locks down and pauses enforcement.
* **Fast Win32 Process Inspection**: Uses `PROCESS_QUERY_LIMITED_INFORMATION` and `QueryFullProcessImageNameA` to reliably inspect active windows and elevated/UWP processes.
* **Multi-Browser URL Detection**: Uses Microsoft UI Automation (`IUIAutomation`) to extract real-time URLs from Microsoft Edge, Google Chrome, Brave, and Firefox address bars.
* **Non-Blocking Enforcement**: Alerts users asynchronously on a dedicated worker thread and automatically minimizes distracting windows without stalling the background monitor.

### 2. Python Vision & Face Authentication Bridge (`focusguard_ai.py` + `face_auth.py`)
* **Face Detection**: Uses **OpenCV YuNet** (`face_detection_yunet_2023mar.onnx`) for high-speed face detection and 5-point facial landmark extraction (eyes, nose, mouth corners) in < 10 ms on CPU.
* **Feature Embeddings**: Uses **OpenCV SFace** (`face_recognition_sface_2021dec.onnx`) generating 128-dimensional L2-normalized cosine embeddings.
* **Encrypted Template Store**: Saves strictly mathematical embeddings and metadata—**never raw camera images or video frames**. Encrypted using **Windows DPAPI** (`CryptProtectData` / `CryptUnprotectData`), hardware/user-bound to the local Windows user credentials.
* **Liveness & Anti-Spoofing**: Analyzes multi-frame landmark micro-movements and eye aspect ratio variations to reject static paper photos, phone screens, and recorded video replays.
* **Visual Classification**: Interfaces with local **Qwen 2.5-VL** via Ollama for desktop screenshot distraction analysis when URLs and titles are ambiguous.
* **Thread-Safe Architecture**: Dedicated locks prevent webcam face authentication from stalling or degrading screen classification.

---

## HTTP API Specification (`127.0.0.1:8765`)

All endpoints communicate locally using JSON:

| Endpoint | Method | Payload / Parameters | Description |
| :--- | :---: | :--- | :--- |
| `/face/status` | `GET` | *None* | Returns `{"enrolled": bool, "camera_available": bool, "model_loaded": bool, "user_id": str}` |
| `/face/enroll` | `POST` | `{"user_id": "default", "frames": 20}` | Captures live webcam frames, checks liveness, averages embeddings, encrypts with DPAPI, and saves template. Returns `200` or `409 Conflict` if already enrolled. |
| `/face/authenticate` | `POST` | `{"user_id": "default", "timeout_ms": 8000}` | Verifies live webcam frames against stored template + liveness check. Returns `200 {"authenticated": true, "confidence": 0.92}` or `401 {"authenticated": false, "reason": "..."}`. |
| `/face/presence` | `POST` | `{"user_id": "default"}` | Ultra-fast presence verification (< 150 ms). Returns `200 {"present": bool, "confidence": float}`. |
| `/face/reset` | `POST` | `{"user_id": "default"}` | Securely wipes encrypted template from disk. |
| `/classify` | `POST` / `GET` | *None* | Captures desktop screen and classifies user activity with Qwen 2.5-VL. |
| `/health` | `GET` | *None* | Health probe reporting model, backend, and Face Auth readiness. |

---

## Prerequisites

1. **C++ Compiler**: GCC (MinGW-w64), Clang, or MSVC with C++17 support.
2. **Build Tool**: CMake 3.15+ and Ninja or MinGW Makefiles.
3. **Python**: Python 3.9+ with packages in `tools/requirements.txt`.
4. **Webcam**: Standard USB or integrated laptop webcam.
5. **Ollama** *(Optional for AI Vision)*: Installed with model `qwen2.5-vl:3b`.

---

## Building the C++ Core

```powershell
# 1. Configure build with CMake
cmake -B build -G Ninja

# 2. Build binaries
cmake --build build
```

This compiles:
* `build/focusguard_monitor.exe`: The primary background monitoring and face-gated enforcement daemon.
* `build/focusguard_demo.exe`: Policy demonstration CLI.
* `build/face_auth_test.exe`: Automated C++ unit tests for face auth, PIN hashing, and state transitions.

---

## Running FocusGuard

### Step 1: Start the Local Vision & Face Auth Bridge
In a dedicated terminal:
```powershell
# Install Python dependencies
pip install -r tools/requirements.txt

# Start the bridge daemon
python tools/focusguard_ai.py --serve
```

### Step 2: First-Time Face Enrollment
Enroll your face biometrics using either the C++ daemon or Python CLI:
```powershell
# Via C++ daemon:
.\build\focusguard_monitor.exe --enroll

# Or via Python directly:
python tools/focusguard_ai.py --enroll
```
*Look directly at the camera with good lighting and maintain natural subtle movements while 20 frames are processed.*

### Step 3: Launch FocusGuard Monitor
```powershell
.\build\focusguard_monitor.exe
```
* On startup, the **FocusGuard Lock Screen** appears.
* Look at the webcam to automatically authenticate and unlock within 1–2 seconds.
* If the camera is obscured or 3 failed attempts occur, enter the fallback PIN (default: `1234`).

---

## CLI Options

```powershell
.\build\focusguard_monitor.exe --help
```

* `--enroll`: Interactive webcam biometric enrollment.
* `--reset-face`: Reset enrolled biometric template.
* `--lock`: Start daemon in locked mode.
* `--pin <pin>`: Set or update the fallback PIN.
* `--no-face-auth`: Bypass face authentication gate for debugging.

---

## Automated Verification & Testing

FocusGuard includes comprehensive automated test suites for both Python and C++ layers:

### Python Biometric & DPAPI Tests
```powershell
python tools/test_face_auth.py
```
* Validates Windows DPAPI encryption / decryption roundtrip.
* Validates SFace 128-d cosine distance math and similarity thresholds.
* Validates liveness defense (rejects simulated static photos and trivial jitter).
* Validates template persistence, security, and reset workflows.

### C++ State Machine & PIN Hashing Tests
```powershell
cmake --build build --target face_auth_test
.\build\face_auth_test.exe
```
* Validates portable SHA-256 PIN hashing and verification.
* Validates `LOCKED -> AUTHENTICATING -> UNLOCKED -> LOCKED` state transitions.
* Validates non-blocking enforcement pause during lockouts.

---

## Security & Privacy Highlights

* **100% Local**: No biometric data or webcam frames leave your computer.
* **Zero Image Retention**: Raw images are discarded immediately after feature extraction. Only 128 floating-point embedding weights are stored.
* **DPAPI Hardware/User Encryption**: The template file (`tools/face_template.enc`) is encrypted using Windows Data Protection API (DPAPI), bound to the logged-in Windows user.
* **Anti-Spoofing Liveness Defense**: Multi-frame micro-motion and landmark dynamics reject printed photos and digital screens.
* **Fail-Safe Fallback**: Automatic PIN fallback ensures users are never locked out of their system.

---

## License
MIT License
