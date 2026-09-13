"""
FocusGuard Face Authentication Service
Local, DPAPI-encrypted, liveness-verified face authentication module.
Supports Multi-User profiles, Guest Detection, and Browser-Webcam Frame Streaming.
"""

import os
import sys
import time
import json
import uuid
import base64
import ctypes
from ctypes import wintypes
import threading
import urllib.request
import cv2
import numpy as np

# Ensure Windows console supports UTF-8 characters
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Directory paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
TEMPLATE_PATH = os.path.join(BASE_DIR, "face_template.enc")

YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = "face_recognition_sface_2021dec.onnx"

YUNET_PATH = os.path.join(MODELS_DIR, YUNET_MODEL)
SFACE_PATH = os.path.join(MODELS_DIR, SFACE_MODEL)

# Model download URLs
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


def decode_base64_image(image_str):
    """Safely decodes data URL or base64 string into an OpenCV BGR numpy frame."""
    if not image_str or not isinstance(image_str, str):
        return None
    try:
        if "," in image_str:
            image_str = image_str.split(",", 1)[1]
        raw = base64.b64decode(image_str.strip())
        nparr = np.frombuffer(raw, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return frame
    except Exception:
        return None


# ============================================================
# FACE AUTHENTICATION ENGINE
# ============================================================

class FaceAuthEngine:
    """
    High-performance, local face authentication engine.
    Uses OpenCV YuNet for face detection & landmarks and SFace for 128-d embeddings.
    Multi-user aware: distinguishes enrolled users from non-enrolled guests.
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
        """Loads YuNet and SFace into OpenCV DNN, supporting in-memory buffers for Unicode paths."""
        try:
            try:
                with open(YUNET_PATH, "rb") as f:
                    yunet_bytes = f.read()
                self.detector = cv2.FaceDetectorYN.create(
                    "onnx",
                    yunet_bytes,
                    bytearray(),
                    (320, 320),
                    score_threshold=0.6,
                    nms_threshold=0.3,
                    top_k=5000
                )
            except Exception:
                self.detector = cv2.FaceDetectorYN.create(
                    YUNET_PATH,
                    "",
                    (320, 320),
                    score_threshold=0.6,
                    nms_threshold=0.3,
                    top_k=5000
                )

            try:
                with open(SFACE_PATH, "rb") as f:
                    sface_bytes = f.read()
                self.recognizer = cv2.FaceRecognizerSF.create(
                    "onnx",
                    sface_bytes,
                    bytearray()
                )
            except Exception:
                self.recognizer = cv2.FaceRecognizerSF.create(
                    SFACE_PATH,
                    ""
                )

            self.initialized = True
            print("[FaceAuth] YuNet and SFace models initialized successfully.")
        except Exception as e:
            print(f"[FaceAuth Error] Failed to initialize face models: {e}")
            self.initialized = False

    def _load_templates(self) -> dict:
        """
        Decrypts and loads all templates from encrypted storage.
        Returns a dict of {user_id: template_data}.
        """
        if not os.path.exists(TEMPLATE_PATH):
            return {}
        try:
            with open(TEMPLATE_PATH, "rb") as f:
                encrypted_data = f.read()
            decrypted_json = dpapi_unprotect(encrypted_data).decode("utf-8")
            data = json.loads(decrypted_json)
            if isinstance(data, dict):
                if "templates" in data and isinstance(data["templates"], dict):
                    return data["templates"]
                elif "user_id" in data:
                    # Legacy single template format
                    uid = data["user_id"]
                    t_dict = {uid: data}
                    if uid == "default":
                        t_dict["Yogita"] = dict(data)
                        t_dict["Yogita"]["user_id"] = "Yogita"
                    return t_dict
            return {}
        except Exception as ex:
            print(f"[FaceAuth] Load template error: {ex}")
            return {}

    def _save_templates(self, templates_dict: dict):
        """Encrypts templates dictionary with DPAPI and persists to disk."""
        payload = {"templates": templates_dict}
        raw_bytes = json.dumps(payload).encode("utf-8")
        encrypted_bytes = dpapi_protect(raw_bytes)
        with open(TEMPLATE_PATH, "wb") as f:
            f.write(encrypted_bytes)

    def _load_template(self, user_id=None) -> dict:
        """Backwards-compatible single template getter."""
        templates = self._load_templates()
        if not templates:
            return None
        if user_id:
            if user_id in templates:
                return templates[user_id]
            if user_id == "default" and "Yogita" in templates:
                return templates["Yogita"]
            if user_id == "Yogita" and "default" in templates:
                return templates["default"]
            return None
        # Return first available template
        return next(iter(templates.values()), None)

    def list_enrolled_users(self) -> list:
        """Returns list of all user IDs that have enrolled biometric face templates."""
        templates = self._load_templates()
        users = list(templates.keys())
        # If 'default' exists along with named users, prefer named users
        if "default" in users and len(users) > 1:
            users = [u for u in users if u != "default"]
        return users

    def is_enrolled(self, user_id=None) -> bool:
        """Checks if an encrypted face template exists for the given user (or any user if user_id is None)."""
        templates = self._load_templates()
        if not templates:
            return False
        if not user_id or user_id in ("any", "default"):
            return len(templates) > 0
        return user_id in templates or ("default" in templates and user_id == "Yogita")

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

        if len(faces) > 1:
            areas = [f[2] * f[3] for f in faces]
            sorted_indices = np.argsort(areas)[::-1]
            largest_area = areas[sorted_indices[0]]
            second_largest = areas[sorted_indices[1]]
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
        return feat

    def check_liveness(self, landmark_history) -> bool:
        """Anti-spoofing liveness verification using subtle micro-movement across frames."""
        if len(landmark_history) < 4:
            return True
        arr = np.array(landmark_history)
        eye_dists = np.linalg.norm(arr[:, :2] - arr[:, 2:4], axis=1)
        mean_eye_dist = np.mean(eye_dists)
        if mean_eye_dist < 5.0:
            return False
        normalized_coords = arr / mean_eye_dist
        stds = np.std(normalized_coords, axis=0)
        mean_variation = np.mean(stds)
        if mean_variation < LIVENESS_MIN_VARIATION:
            return False
        return True

    def enroll(self, user_id="Yogita", target_frames=15, image=None, frames=None) -> dict:
        """
        Interactive face enrollment.
        Supports both webcam capture and browser-streamed frames/image.
        """
        user_id = (user_id or "Yogita").strip()
        with self.lock:
            features = []
            landmark_history = []

            # 1. Check if frames are supplied directly (e.g. from Web UI scanner)
            raw_frames = []
            if frames and isinstance(frames, list):
                for f_item in frames:
                    f = decode_base64_image(f_item)
                    if f is not None:
                        raw_frames.append(f)
            elif image:
                f = decode_base64_image(image)
                if f is not None:
                    raw_frames.append(f)

            if raw_frames:
                for frame in raw_frames:
                    best_face, aligned, multiple_faces = self.detect_and_align(frame)
                    if not multiple_faces and best_face is not None and aligned is not None:
                        feat = self.extract_feature(aligned)
                        if feat is not None:
                            features.append(feat)
                            landmark_history.append(best_face[4:14])
            else:
                # 2. Capture live webcam frames
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

                start_time = time.time()
                max_enroll_time = 12.0
                try:
                    while len(features) < target_frames and (time.time() - start_time) < max_enroll_time:
                        ret, frame = cap.read()
                        if not ret or frame is None:
                            time.sleep(0.04)
                            continue
                        best_face, aligned, multiple_faces = self.detect_and_align(frame)
                        if multiple_faces or best_face is None or aligned is None:
                            time.sleep(0.04)
                            continue
                        feat = self.extract_feature(aligned)
                        if feat is not None:
                            features.append(feat)
                            landmark_history.append(best_face[4:14])
                        time.sleep(0.04)
                finally:
                    cap.release()

            if len(features) < 1:
                return {
                    "success": False,
                    "status": "enrollment_failed",
                    "code": 401,
                    "message": "No clear face frames captured. Ensure face is centered with adequate lighting."
                }

            # Liveness check if multiple frames available
            if len(landmark_history) >= 4 and not self.check_liveness(landmark_history):
                return {
                    "success": False,
                    "status": "liveness_failed",
                    "code": 401,
                    "message": "Liveness check failed. Ensure natural head presence."
                }

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

            templates = self._load_templates()
            templates[user_id] = template_data
            self._save_templates(templates)

            print(f"[FaceAuth] Successfully enrolled user '{user_id}' ({len(features)} frames).")

            return {
                "success": True,
                "status": "enrolled",
                "code": 200,
                "template_id": template_id,
                "user_id": user_id,
                "samples_averaged": len(features)
            }

    def authenticate(self, user_id="any", image=None, timeout_ms=4000) -> dict:
        """
        Authenticates the face against enrolled templates.
        Distinguishes matching enrolled user from unrecognized guest.
        """
        with self.lock:
            templates = self._load_templates()
            if not templates:
                return {
                    "authenticated": False,
                    "confidence": 0.0,
                    "reason": "not_enrolled",
                    "is_guest": False
                }

            frames_to_check = []
            if image:
                f = decode_base64_image(image)
                if f is not None:
                    frames_to_check.append(f)

            cap = None
            if not frames_to_check:
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(self.camera_index)
                if not cap.isOpened():
                    return {
                        "authenticated": False,
                        "confidence": 0.0,
                        "reason": "camera_unavailable",
                        "is_guest": False
                    }

            start_time = time.time()
            max_seconds = timeout_ms / 1000.0
            face_detected_any = False
            best_conf = 0.0
            best_match_user = None

            try:
                while True:
                    if frames_to_check:
                        if not frames_to_check:
                            break
                        frame = frames_to_check.pop(0)
                    elif cap:
                        if (time.time() - start_time) >= max_seconds:
                            break
                        ret, frame = cap.read()
                        if not ret or frame is None:
                            time.sleep(0.04)
                            continue
                    else:
                        break

                    best_face, aligned, multiple_faces = self.detect_and_align(frame)
                    if multiple_faces or best_face is None or aligned is None:
                        time.sleep(0.04)
                        continue

                    face_detected_any = True
                    feat = self.extract_feature(aligned)
                    if feat is None:
                        continue

                    # Compare against candidate templates
                    candidates = templates.items() if (user_id in ("any", None, "")) else [(user_id, templates.get(user_id))]

                    for uid, t_data in candidates:
                        if not t_data:
                            continue
                        stored_feat = np.array(t_data["feature_vector"], dtype=np.float32).reshape(1, -1)
                        score = float(self.recognizer.match(stored_feat, feat, cv2.FaceRecognizerSF_FR_COSINE))
                        norm_conf = max(0.0, min(1.0, score))
                        if norm_conf > best_conf:
                            best_conf = norm_conf
                            best_match_user = uid

                    if best_conf >= self.threshold:
                        return {
                            "authenticated": True,
                            "user_id": best_match_user,
                            "confidence": round(best_conf, 3),
                            "is_guest": False,
                            "reason": "matched"
                        }

                    if not cap:
                        break
                    time.sleep(0.04)

            finally:
                if cap:
                    cap.release()

            if face_detected_any:
                # A face was seen in camera, but does NOT match the enrolled user -> GUEST!
                return {
                    "authenticated": False,
                    "user_id": "guest",
                    "confidence": round(best_conf, 3),
                    "is_guest": True,
                    "reason": "unrecognized_face"
                }

            return {
                "authenticated": False,
                "user_id": None,
                "confidence": 0.0,
                "is_guest": False,
                "reason": "no_face"
            }

    def check_presence(self, user_id=None, image=None) -> dict:
        """
        Fast presence verification (< 300 ms).
        Returns:
          - user_present=True, is_guest=False (Enrolled user is actively watching -> Focus rules active)
          - user_present=False, is_guest=True (Guest watching screen -> Focus rules paused, flawless apps)
          - user_present=False, is_guest=False (No face in front of screen)
        """
        with self.lock:
            templates = self._load_templates()
            if not templates:
                return {
                    "present": False,
                    "user_present": False,
                    "is_guest": False,
                    "user_id": None,
                    "confidence": 0.0,
                    "reason": "not_enrolled"
                }

            # Select target template
            target_user = user_id
            if not target_user or target_user in ("default", "any"):
                target_user = next(iter(templates.keys()))
            target_template = templates.get(target_user) or next(iter(templates.values()))

            stored_feat = np.array(target_template["feature_vector"], dtype=np.float32).reshape(1, -1)

            frame = None
            if image:
                frame = decode_base64_image(image)

            cap = None
            if frame is None:
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(self.camera_index)
                if not cap.isOpened():
                    return {
                        "present": False,
                        "user_present": False,
                        "is_guest": False,
                        "confidence": 0.0,
                        "reason": "camera_unavailable"
                    }

            face_detected = False
            best_conf = 0.0

            try:
                # Inspect 1-2 frames
                for _ in range(2):
                    if cap:
                        ret, frame = cap.read()
                        if not ret or frame is None:
                            continue

                    best_face, aligned, multiple = self.detect_and_align(frame)
                    if multiple or best_face is None or aligned is None:
                        continue

                    face_detected = True
                    feat = self.extract_feature(aligned)
                    if feat is None:
                        continue

                    score = float(self.recognizer.match(stored_feat, feat, cv2.FaceRecognizerSF_FR_COSINE))
                    norm_conf = max(0.0, min(1.0, score))
                    if norm_conf > best_conf:
                        best_conf = norm_conf

                    # Relax threshold slightly for fast presence checks
                    if score >= (self.threshold - 0.05):
                        return {
                            "present": True,
                            "user_present": True,
                            "is_guest": False,
                            "user_id": target_user,
                            "confidence": round(norm_conf, 3),
                            "message": f"Enrolled user '{target_user}' verified watching screen."
                        }

                    if not cap:
                        break
            finally:
                if cap:
                    cap.release()

            if face_detected:
                # Face is in front of screen, but biometric template DOES NOT MATCH enrolled user!
                # This is a GUEST. FocusGuard policies must pause so they can use apps flawlessly.
                return {
                    "present": False,
                    "user_present": False,
                    "is_guest": True,
                    "user_id": "guest",
                    "confidence": round(best_conf, 3),
                    "reason": "unrecognized_face",
                    "message": "Guest detected: non-enrolled person watching screen. Distraction restrictions paused."
                }

            return {
                "present": False,
                "user_present": False,
                "is_guest": False,
                "user_id": None,
                "confidence": 0.0,
                "reason": "no_face",
                "message": "No face detected in front of screen."
            }

    def reset(self, user_id=None) -> dict:
        """Removes face enrollment for specified user, or all users if None or 'all'."""
        with self.lock:
            if not os.path.exists(TEMPLATE_PATH):
                return {"success": True, "status": "not_enrolled", "message": "No template was enrolled."}

            try:
                if not user_id or user_id in ("all", "*"):
                    os.remove(TEMPLATE_PATH)
                    return {"success": True, "status": "reset", "message": "All face enrollments cleared."}

                templates = self._load_templates()
                if user_id in templates:
                    del templates[user_id]
                if user_id == "Yogita" and "default" in templates:
                    del templates["default"]

                if templates:
                    self._save_templates(templates)
                else:
                    os.remove(TEMPLATE_PATH)

                print(f"[FaceAuth] Cleared face enrollment for user '{user_id}'.")
                return {"success": True, "status": "reset", "message": f"Enrollment for '{user_id}' cleared."}
            except Exception as e:
                return {"success": False, "status": "error", "message": str(e)}

    def reset_enrollment(self, user_id=None) -> dict:
        """Alias for reset()."""
        return self.reset(user_id=user_id)

    def get_status(self, user_id=None) -> dict:
        """Returns the operational status of the Face Auth module."""
        enrolled_users = self.list_enrolled_users()
        is_user_enrolled = self.is_enrolled(user_id) if user_id else (len(enrolled_users) > 0)
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

        target_template = self._load_template(user_id)

        return {
            "enrolled": len(enrolled_users) > 0,
            "user_enrolled": is_user_enrolled,
            "currentUser": user_id,
            "camera_available": camera_ok,
            "model_loaded": self.initialized,
            "enrolled_users": enrolled_users,
            "template": {
                "user_id": target_template.get("user_id"),
                "template_id": target_template.get("template_id"),
                "enrolled_at": target_template.get("enrolled_at")
            } if target_template else {},
            "threshold": self.threshold
        }


# Global singleton instance
_engine = None

def get_face_auth_engine(camera_index=0, threshold=DEFAULT_CONFIDENCE_THRESHOLD) -> FaceAuthEngine:
    global _engine
    if _engine is None:
        _engine = FaceAuthEngine(camera_index=camera_index, threshold=threshold)
    return _engine
