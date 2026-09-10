"""
FocusGuard AI Screen Capture Test (Qwen 2.5-VL)
"""

import os
import time
import base64
import json
import re
import cv2
import requests
import numpy as np

try:
    import dxcam
    HAS_DXCAM = True
except ImportError:
    HAS_DXCAM = False

from PIL import ImageGrab

print("=" * 40)
print("     FOCUS GUARD QWEN 2.5-VL TEST")
print("=" * 40)

SAVE_DIR = "screen_frames"
os.makedirs(SAVE_DIR, exist_ok=True)

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5vl:3b"
CHANGE_THRESHOLD = 8.0
AI_COOLDOWN = 5


def grab_desktop_frame():
    """Captures a frame using PIL/dxcam."""
    img = ImageGrab.grab()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def analyze_screen(image_path):
    print("[AI] Analyzing screen with Qwen 2.5-VL...")
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None

        h, w = image.shape[:2]
        target_w = 1024
        target_h = int(h * (target_w / w))
        resized = cv2.resize(image, (target_w, target_h))

        success, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not success:
            print("[AI ERROR] Failed to encode image.")
            return None

        image_base64 = base64.b64encode(encoded.tobytes()).decode("utf-8")

        prompt = """You are the visual intelligence system of FocusGuard.
Analyze the screenshot and classify the activity into exactly one of:
PRODUCTIVE
DISTRACTION
NEUTRAL
UNKNOWN

Return ONLY valid JSON in this exact format:
{
  "activity": "short description",
  "classification": "PRODUCTIVE",
  "confidence": 0.95,
  "reason": "short explanation"
}"""

        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64]
                }
            ],
            "stream": False,
            "options": {"temperature": 0.0}
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        if response.status_code != 200:
            print(f"[AI ERROR] Ollama returned {response.status_code}")
            return None

        data = response.json()
        raw_response = data.get("message", {}).get("content", "").strip()

        json_match = re.search(r"\{[\s\S]*\}", raw_response)
        if not json_match:
            print(f"[AI ERROR] Invalid JSON: {raw_response}")
            return None

        result = json.loads(json_match.group(0))
        print("\n[AI RESULT]")
        print("Activity      :", result.get("activity", "Unknown"))
        print("Classification :", result.get("classification", "UNKNOWN"))
        print("Confidence     :", result.get("confidence", 0))
        print("Reason         :", result.get("reason", ""))
        print()
        return result

    except Exception as e:
        print(f"[AI ERROR] {e}")
        return None


def main():
    print("Starting capture test...")
    previous_frame = None
    saved_count = 0
    last_ai_time = 0

    try:
        while True:
            frame = grab_desktop_frame()
            if frame is None:
                time.sleep(0.1)
                continue

            current_time = time.time()

            if previous_frame is None:
                previous_frame = frame.copy()
                filename = os.path.join(SAVE_DIR, f"qwen_frame_{saved_count:04d}.jpg")
                cv2.imwrite(filename, frame)
                saved_count += 1
                analyze_screen(filename)
                last_ai_time = current_time
                time.sleep(0.5)
                continue

            # Screen change comparison
            curr_small = cv2.resize(frame, (320, 180))
            prev_small = cv2.resize(previous_frame, (320, 180))
            curr_gray = cv2.cvtColor(curr_small, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.cvtColor(prev_small, cv2.COLOR_BGR2GRAY)

            change_score = cv2.absdiff(curr_gray, prev_gray).mean()

            if change_score >= CHANGE_THRESHOLD and (current_time - last_ai_time >= AI_COOLDOWN):
                previous_frame = frame.copy()
                saved_count += 1
                filename = os.path.join(SAVE_DIR, f"qwen_frame_{saved_count:04d}.jpg")
                cv2.imwrite(filename, frame)
                print(f"\n[SCREEN CHANGE] {change_score:.2f} -> Saved {filename}")
                analyze_screen(filename)
                last_ai_time = current_time

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nCapture stopped.")


if __name__ == "__main__":
    main()