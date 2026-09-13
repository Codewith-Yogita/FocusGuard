# FocusGuard UI Dashboard (v2.1 with Face ID & Presence Auto-Lock)

A modern web dashboard for **FocusGuard** with live focus monitoring, distraction escalation radar (10s Warning / 30s Alert / 60s Intervention), policy rules management, **Face Recognition Login**, **Presence Auto-Lock (60s)**, **Liveness Anti-Spoofing**, **Qwen/Gemma Multimodal AI Inspector**, and Light/Dark themes.

---

## 🚀 Quick Start (macOS & Windows)

### 1. Launch Server
From the `ui/` directory:
```bash
python3 server.py
```
Open the URL printed in the console (e.g., [http://localhost:8000](http://localhost:8000) or [http://localhost:8001](http://localhost:8001)) in your browser.

---

## 🌟 Key Features

1. **Biometric Face Recognition & Lock Screen (New from feature branch)**:
   - **OpenCV YuNet & SFace (128-d vector)** local face detection and recognition.
   - **Cross-Platform Security**: Automatic PBKDF2/DPAPI encryption for template safety on macOS, Linux, and Windows.
   - **Presence Auto-Lock (60s)**: Automatically locks session when user leaves camera view.
   - **Liveness Anti-Spoofing Defense**: Micro-motion & multi-frame blink validation to reject printed photo attacks.
   - **Fallback Security PIN**: 4-digit PIN unlock (Default: `1234`) with instant PIN change in UI.

2. **Dark & Light Themes**:
   - One-click toggle in the header with auto OS-preference detection and persistence.

3. **Live Monitor & Distraction Escalation Meter**:
   - Real-time application and window target tracking.
   - Classification indicator: `PRODUCTIVE`, `DISTRACTION`, `NEUTRAL`, `UNKNOWN`.
   - 3-tier distraction escalation progress bar:
     - ⚠️ **10s**: Warning
     - 🚨 **30s**: Strong Alert
     - 🛑 **60s**: FocusGuard Refocus Intervention & Lockout.
   - Interactive Activity Simulator.

4. **Policy Studio**:
   - Manage application restriction rules (`BLOCK`, `CONTENT_AWARE`, `ALLOW`).
   - Configure custom max distraction limits and lockout cooldown durations.
   - Presets for **Strict Exam Mode** and **Balanced Dev Mode**.

5. **Vision AI & OCR Inspector**:
   - Multimodal AI visual screen inspector (`Qwen 2.5-VL` / `Gemma 3`).
   - Screen change score tracking (`> 8.0`) and extracted OCR token tags.

6. **Analytics & Productivity Insights**:
   - Interactive time distribution and app ranking charts.
