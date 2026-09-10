"""
FocusGuard Vision Intelligence Service
Powered by Qwen 2.5-VL
"""

import sys
import os
import time
import base64
import json
import re
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

import cv2
import requests
import numpy as np

# Capture backends
try:
    import dxcam
    HAS_DXCAM = True
except ImportError:
    HAS_DXCAM = False

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

from PIL import ImageGrab

# Face authentication engine
try:
    from tools.face_auth import get_face_auth_engine
except ImportError:
    try:
        from face_auth import get_face_auth_engine
    except ImportError:
        get_face_auth_engine = None



# Default configuration
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen2.5vl:3b"
DEFAULT_PORT = 8765
CHANGE_THRESHOLD = 8.0
AI_COOLDOWN_SECONDS = 4.0


class ScreenCapturer:
    """Captures desktop screen with DirectX (dxcam) and falls back to MSS / PIL."""

    def __init__(self):
        self.backend = None
        self.camera = None
        self.sct = None

        if HAS_DXCAM:
            try:
                self.camera = dxcam.create(output_color="BGR")
                if self.camera is not None:
                    self.backend = "dxcam"
                    print("[Capture] Using DirectX (dxcam) acceleration.")
            except Exception as e:
                print(f"[Capture] dxcam initialization failed: {e}. Falling back.")

        if self.backend is None and HAS_MSS:
            try:
                self.sct = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
                self.backend = "mss"
                print("[Capture] Using MSS screen capture.")
            except Exception as e:
                print(f"[Capture] mss initialization failed: {e}. Falling back to PIL.")

        if self.backend is None:
            self.backend = "pil"
            print("[Capture] Using standard PIL ImageGrab.")

    def grab_frame(self):
        """Returns BGR numpy array of full desktop or None on failure."""
        try:
            if self.backend == "dxcam":
                frame = self.camera.grab()
                if frame is not None:
                    return frame

            if self.backend == "mss":
                monitor = self.sct.monitors[1]
                sct_img = self.sct.grab(monitor)
                frame = np.array(sct_img)
                return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            # Fallback: PIL
            img = ImageGrab.grab()
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        except Exception as ex:
            print(f"[Capture Error] {ex}")
            return None


class QwenVisionClassifier:
    """Interfaces with Qwen 2.5-VL to classify user screen activities."""

    def __init__(self, ollama_url=DEFAULT_OLLAMA_URL, model=DEFAULT_MODEL):
        self.ollama_url = ollama_url
        self.model = model
        self.last_analysis_time = 0.0
        self.last_result = {
            "activity": "Unknown",
            "classification": "UNKNOWN",
            "confidence": 0.0,
            "reason": "Not yet evaluated"
        }

    def analyze_frame(self, frame_bgr):
        """Analyzes a screen frame using Qwen 2.5-VL."""
        if frame_bgr is None:
            return None

        # Resize for optimal Qwen 2.5-VL token usage while preserving text sharpness
        h, w = frame_bgr.shape[:2]
        target_w = 1024
        target_h = int(h * (target_w / w))
        resized = cv2.resize(frame_bgr, (target_w, target_h), interpolation=cv2.INTER_AREA)

        # Encode to JPEG in-memory
        success, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not success:
            return None

        image_b64 = base64.b64encode(encoded.tobytes()).decode("utf-8")

        prompt = """You are the visual intelligence classifier for FocusGuard.
Analyze this desktop screenshot and classify the user's current activity into exactly one category:
- PRODUCTIVE (programming, IDE, software development, DSA, reading documentation, academic lectures, educational research)
- DISTRACTION (YouTube Shorts, Instagram Reels, social media feeds, video games, entertainment streaming)
- NEUTRAL (desktop navigation, utility apps, music playback, file manager)
- UNKNOWN (unclear or blank content)

Rules:
1. YouTube Shorts or vertical short-form videos are ALWAYS DISTRACTION.
2. Code editors, terminals, technical docs, and educational courses are PRODUCTIVE.
3. Respond ONLY with a valid JSON object in this exact schema:
{
  "activity": "<short 3-5 word description>",
  "classification": "<PRODUCTIVE|DISTRACTION|NEUTRAL|UNKNOWN>",
  "confidence": <float between 0.0 and 1.0>,
  "reason": "<brief justification>"
}"""

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64]
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.0
            }
        }

        try:
            resp = requests.post(self.ollama_url, json=payload, timeout=20)
            if resp.status_code != 200:
                print(f"[Qwen API Error] HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            data = resp.json()
            raw_text = data.get("message", {}).get("content", "").strip()

            # Robust JSON extraction using regex
            json_match = re.search(r"\{[\s\S]*\}", raw_text)
            if not json_match:
                print(f"[Qwen Parse Error] No JSON found in response: {raw_text[:200]}")
                return None

            parsed = json.loads(json_match.group(0))

            # Validate fields
            classification = str(parsed.get("classification", "UNKNOWN")).upper()
            if classification not in ("PRODUCTIVE", "DISTRACTION", "NEUTRAL", "UNKNOWN"):
                classification = "UNKNOWN"

            result = {
                "activity": str(parsed.get("activity", "Desktop Activity")),
                "classification": classification,
                "confidence": float(parsed.get("confidence", 0.8)),
                "reason": str(parsed.get("reason", ""))
            }

            self.last_analysis_time = time.time()
            self.last_result = result
            return result

        except requests.exceptions.ConnectionError:
            print(f"[Qwen Offline] Could not connect to Ollama at {self.ollama_url}.")
            return None
        except Exception as ex:
            print(f"[Qwen Exception] {ex}")
            return None


class FocusGuardAIServer(BaseHTTPRequestHandler):
    """Local HTTP API bridge for the C++ FocusGuard Monitor."""

    capturer = None
    classifier = None
    face_engine = None
    lock = threading.Lock()

    def _read_json_body(self):
        """Helper to parse JSON payload from request body."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                raw = self.rfile.read(length).decode("utf-8")
                return json.loads(raw)
        except Exception as e:
            print(f"[HTTP JSON Parse Error] {e}")
        return {}

    def _send_json_response(self, code, data):
        """Sends a JSON response with status code and standard headers."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._send_json_response(200, {
                "status": "ready",
                "model": self.classifier.model if self.classifier else "none",
                "backend": self.capturer.backend if self.capturer else "none",
                "face_auth": self.face_engine is not None and self.face_engine.initialized
            })
            return

        if self.path == "/classify":
            with self.lock:
                frame = self.capturer.grab_frame() if self.capturer else None
                res = self.classifier.analyze_frame(frame) if self.classifier else None
                if res is None and self.classifier:
                    res = self.classifier.last_result

            self._send_json_response(200, res or {})
            return

        if self.path == "/face/status":
            if self.face_engine:
                status = self.face_engine.get_status()
            else:
                status = {
                    "enrolled": False,
                    "camera_available": False,
                    "model_loaded": False,
                    "user_id": "default"
                }
            self._send_json_response(200, status)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/classify":
            with self.lock:
                frame = self.capturer.grab_frame() if self.capturer else None
                res = self.classifier.analyze_frame(frame) if self.classifier else None
                if res is None and self.classifier:
                    res = self.classifier.last_result

            self._send_json_response(200, res or {})
            return

        if self.path == "/face/enroll":
            if not self.face_engine:
                self._send_json_response(500, {"success": False, "message": "Face engine not initialized"})
                return

            body = self._read_json_body()
            user_id = body.get("user_id", "default")
            frames = int(body.get("frames", 20))
            res = self.face_engine.enroll(user_id=user_id, target_frames=frames)
            code = res.get("code", 200 if res.get("success") else 401)
            self._send_json_response(code, res)
            return

        if self.path == "/face/authenticate":
            if not self.face_engine:
                self._send_json_response(500, {"authenticated": False, "reason": "face_engine_offline"})
                return

            body = self._read_json_body()
            user_id = body.get("user_id", "default")
            timeout_ms = int(body.get("timeout_ms", 8000))
            res = self.face_engine.authenticate(user_id=user_id, timeout_ms=timeout_ms)
            code = 200 if res.get("authenticated") else 401
            self._send_json_response(code, res)
            return

        if self.path == "/face/presence":
            if not self.face_engine:
                self._send_json_response(200, {"present": False, "confidence": 0.0})
                return

            body = self._read_json_body()
            user_id = body.get("user_id", "default")
            res = self.face_engine.check_presence(user_id=user_id)
            self._send_json_response(200, res)
            return

        if self.path == "/face/reset":
            if not self.face_engine:
                self._send_json_response(200, {"success": True})
                return

            body = self._read_json_body()
            user_id = body.get("user_id", "default")
            res = self.face_engine.reset(user_id=user_id)
            self._send_json_response(200, res)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Silence default HTTP server access logs
        return


def run_server(port, model, url):
    capturer = ScreenCapturer()
    classifier = QwenVisionClassifier(ollama_url=url, model=model)
    face_engine = get_face_auth_engine() if get_face_auth_engine else None

    FocusGuardAIServer.capturer = capturer
    FocusGuardAIServer.classifier = classifier
    FocusGuardAIServer.face_engine = face_engine

    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, FocusGuardAIServer)
    print("=" * 55)
    print(f" FocusGuard AI Service Running (Qwen 2.5-VL + FaceAuth)")
    print(f" Listening on: http://127.0.0.1:{port}")
    print(f" Target Model: {model}")
    print(f" Ollama URL  : {url}")
    print(f" Face Auth   : {'ACTIVE (DPAPI + YuNet/SFace)' if (face_engine and face_engine.initialized) else 'OFFLINE'}")
    print("=" * 55)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down AI service...")
    finally:
        httpd.server_close()


def run_test(model, url):
    print(f"[Test] Initializing screen capture and Qwen 2.5-VL ({model})...")
    capturer = ScreenCapturer()
    classifier = QwenVisionClassifier(ollama_url=url, model=model)

    print("[Test] Grabbing screen...")
    frame = capturer.grab_frame()
    if frame is None:
        print("[Test Error] Failed to grab desktop frame.")
        return

    print("[Test] Sending frame to Qwen 2.5-VL...")
    t0 = time.time()
    result = classifier.analyze_frame(frame)
    latency = time.time() - t0

    if result:
        print("\n" + "=" * 40)
        print("     QWEN 2.5-VL TEST RESULT")
        print("=" * 40)
        print(f"Activity      : {result['activity']}")
        print(f"Classification: {result['classification']}")
        print(f"Confidence    : {result['confidence']:.2f}")
        print(f"Reason        : {result['reason']}")
        print(f"Latency       : {latency:.2f}s")
        print("=" * 40 + "\n")
    else:
        print(f"[Test Notice] AI analysis failed or Ollama not running at {url}.")


def run_face_enroll():
    print("[Face Enrollment] Starting interactive face enrollment...")
    engine = get_face_auth_engine() if get_face_auth_engine else None
    if not engine or not engine.initialized:
        print("[Error] Face authentication engine could not be initialized.")
        return
    res = engine.enroll(target_frames=20)
    print("Result:", res)


def run_face_test():
    print("[Face Test] Probing face authentication module...")
    engine = get_face_auth_engine() if get_face_auth_engine else None
    if not engine or not engine.initialized:
        print("[Error] Face authentication engine could not be initialized.")
        return
    status = engine.get_status()
    print("Status:", status)
    if status.get("enrolled"):
        print("[Face Test] Testing authentication (look at camera for up to 5s)...")
        auth_res = engine.authenticate(timeout_ms=5000)
        print("Auth result:", auth_res)
    else:
        print("[Face Test] No face enrolled yet. Run with --enroll to enroll.")


def main():
    parser = argparse.ArgumentParser(description="FocusGuard AI Visual Intelligence & Face Auth Bridge")
    parser.add_argument("--serve", action="store_true", help="Start local HTTP classification & face service")
    parser.add_argument("--test", action="store_true", help="Run a single screen capture test")
    parser.add_argument("--enroll", action="store_true", help="Run interactive webcam face enrollment")
    parser.add_argument("--test-face", action="store_true", help="Test face authentication module")
    parser.add_argument("--reset-face", action="store_true", help="Reset enrolled face template")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port (default: {DEFAULT_PORT})")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"Model name (default: {DEFAULT_MODEL})")
    parser.add_argument("--url", type=str, default=DEFAULT_OLLAMA_URL, help="Ollama API URL")

    args = parser.parse_args()

    if args.enroll:
        run_face_enroll()
    elif args.test_face:
        run_face_test()
    elif args.reset_face:
        engine = get_face_auth_engine() if get_face_auth_engine else None
        if engine:
            print("Reset:", engine.reset())
    elif args.test:
        run_test(args.model, args.url)
    elif args.serve:
        run_server(args.port, args.model, args.url)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

