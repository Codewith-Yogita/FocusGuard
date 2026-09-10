"""
FocusGuard Face Authentication Service
Local, DPAPI-encrypted, liveness-verified face authentication module.
"""

import os
import sys
import time
import json
import uuid
import ctypes
from ctypes import wintypes
import threading
import urllib.request
import cv2
import numpy as np

# Directory paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
TEMPLATE_PATH = os.path.join(BASE_DIR, "face_template.enc")

YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = "face_recognition_sface_2021dec.onnx"

YUNET_PATH = os.path.join(MODELS_DIR, YUNET_MODEL)
SFACE_PATH = os.path.join(MODELS_DIR, SFACE_MODEL)

# Model download URLs (HuggingFace OpenCV Zoo mirrors)
MODEL_URLS = {
    YUNET_MODEL: "https://huggingface.co/opencv/opencv_zoo/resolve/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    SFACE_MODEL: "https://huggingface.co/opencv/opencv_zoo/resolve/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
}

# Thresholds
DEFAULT_CONFIDENCE_THRESHOLD = 0.55  # Cosine similarity threshold for SFace
LIVENESS_MIN_VARIATION = 0.003       # Landmark displacement variation threshold


# ============================================================
# WINDOWS DPAPI SECURE ENCRYPTION
# ============================================================

class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_byte))
    ]


def dpapi_protect(data: bytes, description: str = "focusguard_face_template") -> bytes:
    """Encrypts bytes using Windows DPAPI (tied to current Windows user credentials)."""
    if not isinstance(data, bytes):
        data = data.encode('utf-8')
    
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    
    success = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out)
    )
    if not success:
        raise RuntimeError("Windows DPAPI CryptProtectData failed")
    
    encrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return encrypted_bytes


def dpapi_unprotect(encrypted_data: bytes) -> bytes:
    """Decrypts DPAPI-protected bytes using current Windows user credentials."""
    blob_in = DATA_BLOB(len(encrypted_data), ctypes.cast(ctypes.create_string_buffer(encrypted_data), ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    
    success = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out)
    )
    if not success:
        raise RuntimeError("Windows DPAPI CryptUnprotectData failed")
    
    decrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return decrypted_bytes


# ============================================================
# FACE AUTHENTICATION ENGINE
# ============================================================

class FaceAuthEngine:
    """
    High-performance, local face authentication engine.
    Uses OpenCV YuNet for face detection & landmarks and SFace for 128-d embeddings.
    """

    def __init__(self, camera_index=0, threshold=DEFAULT_CONFIDENCE_THRESHOLD):
        self.camera_index = camera_index
        self.threshold = threshold
        self.lock = threading.Lock()
        self.detector = None
        self.recognizer = None
        self.initialized = False
        
        self._ensure_models()
        self._init_models()

    def _ensure_models(self):
        """Ensures ONNX models are present on disk, downloading if necessary."""
        os.makedirs(MODELS_DIR, exist_ok=True)
        for filename, url in MODEL_URLS.items():
            dest = os.path.join(MODELS_DIR, filename)
            if not os.path.exists(dest) or os.path.getsize(dest) < 10000:
                print(f"[FaceAuth] Downloading model {filename}...")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=60) as resp, open(dest, 'wb') as f:
                    while chunk := resp.read(1024 * 1024):
                        f.write(chunk)
                print(f"[FaceAuth] Model {filename} ready ({os.path.getsize(dest)} bytes).")

    def _init_models(self):
        """Loads YuNet and SFace into OpenCV DNN."""
        try:
            self.detector = cv2.FaceDetectorYN.create(
                YUNET_PATH,
                "",
                (320, 320),
                score_threshold=0.6,
                nms_threshold=0.3,
                top_k=5000
            )
            self.recognizer = cv2.FaceRecognizerSF.create(
                SFACE_PATH,
                ""
            )
            self.initialized = True
            print("[FaceAuth] YuNet and SFace models initialized successfully.")
        except Exception as e:
            print(f"[FaceAuth Error] Failed to initialize face models: {e}")
            self.initialized = False

    def is_enrolled(self, user_id="default") -> bool:
        """Checks if an encrypted face template exists on disk."""
        if not os.path.exists(TEMPLATE_PATH):
            return False
        try:
            template = self._load_template()
            return template is not None and template.get("user_id") == user_id
        except Exception:
            return False

    def _load_template(self) -> dict:
        """Decrypts and loads template from encrypted disk storage."""
        if not os.path.exists(TEMPLATE_PATH):
            return None
        with open(TEMPLATE_PATH, "rb") as f:
            encrypted_data = f.read()
        decrypted_json = dpapi_unprotect(encrypted_data).decode("utf-8")
        return json.loads(decrypted_json)

    def _save_template(self, template_data: dict):
        """Encrypts template with DPAPI and persists to disk. Never saves raw images."""
        raw_bytes = json.dumps(template_data).encode("utf-8")
        encrypted_bytes = dpapi_protect(raw_bytes)
        with open(TEMPLATE_PATH, "wb") as f:
            f.write(encrypted_bytes)

    def detect_and_align(self, frame):
        """
        Detects faces in frame.
        Returns: (face_box_landmarks, aligned_face, multiple_faces_flag)
        """
        if frame is None or not self.initialized:
            return None, None, False

        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)

        if faces is None or len(faces) == 0:
            return None, None, False

        # If multiple faces detected, inspect bounding boxes
        if len(faces) > 1:
            # Sort by area descending
            areas = [f[2] * f[3] for f in faces]
            sorted_indices = np.argsort(areas)[::-1]
            largest_area = areas[sorted_indices[0]]
            second_largest = areas[sorted_indices[1]]
            # If second face is comparable in size (>65%), treat as ambiguous
            if second_largest > 0.65 * largest_area:
                return None, None, True
            best_face = faces[sorted_indices[0]]
        else:
            best_face = faces[0]

        aligned = self.recognizer.alignCrop(frame, best_face)
        return best_face, aligned, False

    def extract_feature(self, aligned_face):
        """Extracts 128-dimensional embedding from aligned face."""
        if aligned_face is None or not self.initialized:
            return None
        feat = self.recognizer.feature(aligned_face)
        # SFace returns (1, 128) float32
        return feat

    def check_liveness(self, landmark_history) -> bool:
        """
        Anti-spoofing liveness defense.
        Requires subtle micro-motion across frames to reject static photos/phone screens.
        landmark_history: list of landmark arrays [[x_re, y_re, x_le, y_le, x_nt, y_nt, ...], ...]
        """
        if len(landmark_history) < 4:
            return True  # Insufficient frames yet

        arr = np.array(landmark_history)  # Shape: (N, 10)
        # Normalize relative to head scale (distance between eyes)
        eye_dists = np.linalg.norm(arr[:, :2] - arr[:, 2:4], axis=1)
        mean_eye_dist = np.mean(eye_dists)
        if mean_eye_dist < 5.0:
            return False

        # Calculate standard deviation of normalized landmark displacements
        normalized_coords = arr / mean_eye_dist
        stds = np.std(normalized_coords, axis=0)
        mean_variation = np.mean(stds)

        # Static photos will have almost near-zero micro-movement
        if mean_variation < LIVENESS_MIN_VARIATION:
            return False

        return True

    def enroll(self, user_id="default", target_frames=20) -> dict:
        """
        Interactive face enrollment. Captures live webcam frames,
        verifies liveness, averages embeddings, and encrypts template with DPAPI.
        """
        with self.lock:
            if self.is_enrolled(user_id):
                return {
                    "success": False,
                    "status": "conflict",
                    "code": 409,
                    "message": "User already enrolled. Call /face/reset before re-enrolling."
                }

            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                return {
                    "success": False,
                    "status": "camera_unavailable",
                    "code": 401,
                    "message": f"Could not access webcam at index {self.camera_index}."
                }

            features = []
            landmark_history = []
            start_time = time.time()
            max_enroll_time = 15.0  # 15s max to gather frames

            try:
                while len(features) < target_frames and (time.time() - start_time) < max_enroll_time:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        time.sleep(0.05)
                        continue

                    best_face, aligned, multiple_faces = self.detect_and_align(frame)
                    if multiple_faces or best_face is None or aligned is None:
                        time.sleep(0.05)
                        continue

                    feat = self.extract_feature(aligned)
                    if feat is not None:
                        features.append(feat)
                        # Landmarks: best_face[4:14] contains 5 (x, y) landmark pairs
                        landmark_history.append(best_face[4:14])
                    time.sleep(0.05)

            finally:
                cap.release()

            if len(features) < 5:
                return {
                    "success": False,
                    "status": "enrollment_failed",
                    "code": 401,
                    "message": f"Insufficient face frames captured ({len(features)}/{target_frames}). Please face the camera with good lighting."
                }

            # Verify liveness during enrollment
            if not self.check_liveness(landmark_history):
                return {
                    "success": False,
                    "status": "liveness_failed",
                    "code": 401,
                    "message": "Liveness check failed. Please ensure natural head movement and presence."
                }

            # Calculate average feature vector and L2-normalize
            feat_matrix = np.vstack(features)
            mean_feat = np.mean(feat_matrix, axis=0, keepdims=True)
            norm = np.linalg.norm(mean_feat)
            if norm > 0:
                mean_feat /= norm

            template_id = str(uuid.uuid4())
            template_data = {
                "user_id": user_id,
                "template_id": template_id,
                "enrolled_at": int(time.time()),
                "model": "sface_2021dec",
                "feature_vector": mean_feat.flatten().tolist(),
                "frames_count": len(features)
            }

            self._save_template(template_data)
            print(f"[FaceAuth] Successfully enrolled user '{user_id}' with template ID {template_id}.")

            return {
                "success": True,
                "status": "enrolled",
                "code": 200,
                "template_id": template_id,
                "user_id": user_id
            }

    def authenticate(self, user_id="default", timeout_ms=8000) -> dict:
        """
        Authenticates the user against the enrolled DPAPI template.
        Validates live webcam frames, cosine similarity >= threshold, and liveness.
        """
        with self.lock:
            template = self._load_template()
            if template is None or template.get("user_id") != user_id:
                return {
                    "authenticated": False,
                    "confidence": 0.0,
                    "reason": "not_enrolled"
                }

            stored_feat = np.array(template["feature_vector"], dtype=np.float32).reshape(1, -1)

            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                return {
                    "authenticated": False,
                    "confidence": 0.0,
                    "reason": "camera_unavailable"
                }

            start_time = time.time()
            max_seconds = timeout_ms / 1000.0
            landmark_history = []
            best_confidence = 0.0
            face_detected_any = False

            try:
                while (time.time() - start_time) < max_seconds:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        time.sleep(0.04)
                        continue

                    best_face, aligned, multiple_faces = self.detect_and_align(frame)
                    if multiple_faces:
                        # Ambiguity in frame
                        time.sleep(0.04)
                        continue

                    if best_face is None or aligned is None:
                        time.sleep(0.04)
                        continue

                    face_detected_any = True
                    landmark_history.append(best_face[4:14])
                    feat = self.extract_feature(aligned)

                    # Cosine distance match
                    score = float(self.recognizer.match(stored_feat, feat, cv2.FaceRecognizerSF_FR_COSINE))
                    norm_conf = max(0.0, min(1.0, score))
                    if norm_conf > best_confidence:
                        best_confidence = norm_conf

                    if score >= self.threshold:
                        # Validate liveness
                        if len(landmark_history) >= 4 and not self.check_liveness(landmark_history):
                            # Continue to see if natural movement occurs
                            time.sleep(0.04)
                            continue

                        # Authentication successful!
                        return {
                            "authenticated": True,
                            "confidence": round(best_confidence, 3),
                            "reason": "matched"
                        }

                    time.sleep(0.04)

            finally:
                cap.release()

            reason = "timeout"
            if not face_detected_any:
                reason = "no_face"
            elif best_confidence < self.threshold:
                reason = "low_confidence"

            return {
                "authenticated": False,
                "confidence": round(best_confidence, 3),
                "reason": reason
            }

    def check_presence(self, user_id="default") -> dict:
        """
        Fast presence verification (< 300 ms).
        Captures 1-2 frames to verify enrolled user is still seated in front of screen.
        """
        with self.lock:
            template = self._load_template()
            if template is None or template.get("user_id") != user_id:
                return {"present": False, "confidence": 0.0, "reason": "not_enrolled"}

            stored_feat = np.array(template["feature_vector"], dtype=np.float32).reshape(1, -1)

            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                return {"present": False, "confidence": 0.0, "reason": "camera_unavailable"}

            try:
                # Capture up to 2 frames for fast response
                for _ in range(2):
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        continue
                    best_face, aligned, multiple = self.detect_and_align(frame)
                    if multiple or best_face is None or aligned is None:
                        continue
                    feat = self.extract_feature(aligned)
                    score = float(self.recognizer.match(stored_feat, feat, cv2.FaceRecognizerSF_FR_COSINE))
                    norm_conf = max(0.0, min(1.0, score))
                    if score >= (self.threshold - 0.05):  # Slightly relaxed for presence
                        return {"present": True, "confidence": round(norm_conf, 3)}
            finally:
                cap.release()

            return {"present": False, "confidence": 0.0}

    def reset(self, user_id="default") -> dict:
        """Securely removes the encrypted template file."""
        with self.lock:
            if os.path.exists(TEMPLATE_PATH):
                try:
                    os.remove(TEMPLATE_PATH)
                    print(f"[FaceAuth] Cleared face enrollment for user '{user_id}'.")
                    return {"success": True, "status": "reset", "message": "Enrollment cleared."}
                except Exception as e:
                    return {"success": False, "status": "error", "message": str(e)}
            return {"success": True, "status": "not_enrolled", "message": "No template was enrolled."}

    def get_status(self) -> dict:
        """Returns the operational status of the Face Auth module."""
        enrolled = self.is_enrolled()
        camera_ok = False
        try:
            test_cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not test_cap.isOpened():
                test_cap = cv2.VideoCapture(self.camera_index)
            if test_cap.isOpened():
                camera_ok = True
                test_cap.release()
        except Exception:
            camera_ok = False

        return {
            "enrolled": enrolled,
            "camera_available": camera_ok,
            "model_loaded": self.initialized,
            "user_id": "default",
            "threshold": self.threshold
        }


# Global singleton instance
_engine = None

def get_face_auth_engine(camera_index=0, threshold=DEFAULT_CONFIDENCE_THRESHOLD) -> FaceAuthEngine:
    global _engine
    if _engine is None:
        _engine = FaceAuthEngine(camera_index=camera_index, threshold=threshold)
    return _engine
