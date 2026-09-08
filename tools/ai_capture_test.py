from email.mime import image

import dxcam
import cv2
import os
import time
import base64
import json
import requests


print("=" * 40)
print("     FOCUS GUARD AI SCREEN TEST")
print("=" * 40)


# -----------------------------------------
# CONFIGURATION
# -----------------------------------------

SAVE_DIR = "screen_frames"
os.makedirs(SAVE_DIR, exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "gemma3:4b"

CHANGE_THRESHOLD = 8.0

# Analyze at most once every 5 seconds
AI_COOLDOWN = 5

# -----------------------------------------
# SCREEN CAPTURE
# -----------------------------------------

camera = dxcam.create()

camera.start(target_fps=5)

previous_frame = None

frame_count = 0
saved_count = 0

last_ai_time = 0


# -----------------------------------------
# GEMMA SCREEN ANALYSIS
# -----------------------------------------

def analyze_screen(image_path):

    print("[AI] Analyzing screen...")

    try:

        image = cv2.imread(image_path)
        image = cv2.resize(
             image,
              (960, 540)
        )

        success, encoded_image = cv2.imencode(
             ".jpg",
              image,
                [cv2.IMWRITE_JPEG_QUALITY, 70]
        )

        if not success:
            print("[AI ERROR] Failed to encode image.")
            return None

        image_base64 = base64.b64encode(
              encoded_image.tobytes()
        ).decode("utf-8")

        print("[AI] Image size:", len(image_base64) / 1024, "KB")

        prompt = """
You are the visual intelligence system of FocusGuard.

Analyze the screenshot and determine what the user is currently doing.

Classify the activity into exactly one of:

PRODUCTIVE
DISTRACTION
NEUTRAL
UNKNOWN

Focus on the actual visual content of the screen.

Examples:

- Programming / coding / DSA → PRODUCTIVE
- Educational lecture → PRODUCTIVE
- Documentation / technical research → PRODUCTIVE
- YouTube Shorts → DISTRACTION
- Instagram Reels → DISTRACTION
- Entertainment videos → DISTRACTION
- Casual social media browsing → DISTRACTION
- Normal desktop / unclear content → NEUTRAL or UNKNOWN

IMPORTANT:
Do not decide only from the application name or window title.
Use the actual visual content visible in the screenshot.

Return ONLY valid JSON in this exact format:

{
  "activity": "short description",
  "classification": "PRODUCTIVE",
  "confidence": 0.95,
  "reason": "short explanation"
}

Confidence must be between 0 and 1.
"""


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

            "options": {
                "temperature": 0
            }
        }


        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=60
        )


        if response.status_code != 200:

            print(
                f"[AI ERROR] Ollama returned "
                f"{response.status_code}"
            )

            print(response.text)

            return None


        data = response.json()

        raw_response = data["message"]["content"].strip()

        print("[AI RAW]")
        print(raw_response)

        # -----------------------------------------
        # CLEAN GEMMA RESPONSE
        # -----------------------------------------

        if raw_response.startswith("```"):
            raw_response = raw_response.replace(
                "```json",
                ""
            )

            raw_response = raw_response.replace(
                "```",
                ""
            )

            raw_response = raw_response.strip()

        # -----------------------------------------
        # PARSE JSON
        # -----------------------------------------

        try:

            result = json.loads(raw_response)

            print()
            print("[AI RESULT]")
            print(
            "Activity      :",
            result.get("activity", "Unknown")
        )

            print(
            "Classification :",
            result.get("classification", "UNKNOWN")
        )

            print(
            "Confidence     :",
            result.get("confidence", 0)
        )

            print(
            "Reason         :",
            result.get("reason", "")
        )

            print()

            return result

        except json.JSONDecodeError:

            print("[AI ERROR] Gemma returned invalid JSON.")

            return None

        except Exception as e:
            print("[AI ERROR]", e)
            return None

    except Exception as e:
        print(f"[AI ERROR] Failed to analyze screen: {e}")
        return None


# -----------------------------------------
# START
# -----------------------------------------

print("Starting capture...")
print("Switch between VS Code, YouTube, etc.")
print("Press Ctrl+C to stop.\n")


try:

    while True:

        frame = camera.get_latest_frame()


        if frame is None:

            time.sleep(0.1)

            continue


        frame_count += 1


        # -----------------------------------------
        # FIRST FRAME
        # -----------------------------------------

        if previous_frame is None:

            previous_frame = frame.copy()

            filename = os.path.join(
                SAVE_DIR,
                f"ai_frame_{saved_count:04d}.jpg"
            )

            cv2.imwrite(
                filename,
                frame
            )

            saved_count += 1

            print(
                "[INIT] First frame captured"
            )

            # Analyze first frame
            analyze_screen(filename)

            last_ai_time = time.time()

            time.sleep(0.2)

            continue


        # -----------------------------------------
        # SCREEN CHANGE DETECTION
        # -----------------------------------------

        current_small = cv2.resize(
            frame,
            (320, 180)
        )

        previous_small = cv2.resize(
            previous_frame,
            (320, 180)
        )


        current_gray = cv2.cvtColor(
            current_small,
            cv2.COLOR_BGR2GRAY
        )

        previous_gray = cv2.cvtColor(
            previous_small,
            cv2.COLOR_BGR2GRAY
        )


        difference = cv2.absdiff(
            current_gray,
            previous_gray
        )

        change_score = difference.mean()


        # -----------------------------------------
        # MEANINGFUL SCREEN CHANGE
        # -----------------------------------------

        if change_score >= CHANGE_THRESHOLD:

            previous_frame = frame.copy()

            current_time = time.time()


            print(
                f"\n[SCREEN CHANGE] "
                f"{change_score:.2f}"
            )


            # -----------------------------------------
            # AI COOLDOWN
            # -----------------------------------------

            if current_time - last_ai_time >= AI_COOLDOWN:

                saved_count += 1

                filename = os.path.join(
                    SAVE_DIR,
                    f"ai_frame_{saved_count:04d}.jpg"
                )


                cv2.imwrite(
                    filename,
                    frame
                )


                print(
                    f"[CAPTURE] Saved {filename}"
                )


                result = analyze_screen(
                    filename
                )


                last_ai_time = current_time


        time.sleep(0.2)


except KeyboardInterrupt:

    print("\nStopping...")


finally:

    camera.stop()

    print("\nCapture stopped.")

    print(
        f"Frames checked : {frame_count}"
    )

    print(
        f"AI screenshots : {saved_count}"
    )