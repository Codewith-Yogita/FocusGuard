import dxcam
import cv2
import os
import time

print("=" * 40)
print("      FOCUS GUARD SCREEN CAPTURE")
print("=" * 40)

# Folder where changed screenshots will be stored
SAVE_DIR = "screen_frames"
os.makedirs(SAVE_DIR, exist_ok=True)

camera = dxcam.create()

# Start screen capture
camera.start(target_fps=5)

previous_frame = None
frame_count = 0
saved_count = 0

# How different the screen must be before we save it
CHANGE_THRESHOLD = 8.0

print("Starting capture...")
print("Switch between VS Code, YouTube, Chrome, etc.")
print("Press Ctrl+C to stop.\n")

try:
    while True:

        frame = camera.get_latest_frame()

        if frame is None:
            time.sleep(0.1)
            continue

        frame_count += 1

        # First frame
        if previous_frame is None:
            previous_frame = frame.copy()

            filename = os.path.join(
                SAVE_DIR,
                f"frame_{saved_count:04d}.jpg"
            )

            cv2.imwrite(filename, frame)
            saved_count += 1

            print("[INIT] First frame captured")
            time.sleep(0.2)
            continue

        # Resize for faster comparison
        current_small = cv2.resize(
            frame,
            (320, 180)
        )

        previous_small = cv2.resize(
            previous_frame,
            (320, 180)
        )

        # Convert to grayscale
        current_gray = cv2.cvtColor(
            current_small,
            cv2.COLOR_BGR2GRAY
        )

        previous_gray = cv2.cvtColor(
            previous_small,
            cv2.COLOR_BGR2GRAY
        )

        # Calculate average screen difference
        difference = cv2.absdiff(
            current_gray,
            previous_gray
        )

        change_score = difference.mean()

        if change_score >= CHANGE_THRESHOLD:

            saved_count += 1

            filename = os.path.join(
                SAVE_DIR,
                f"frame_{saved_count:04d}.jpg"
            )

            cv2.imwrite(filename, frame)

            print(
                f"[SCREEN CHANGE] "
                f"{change_score:.2f} → saved {filename}"
            )

            # Important:
            # compare the next frame against this new state
            previous_frame = frame.copy()

        time.sleep(0.2)

except KeyboardInterrupt:
    print("\nStopping...")

finally:
    camera.stop()

    print("Capture stopped.")
    print(f"Frames checked : {frame_count}")
    print(f"Screenshots saved: {saved_count}")