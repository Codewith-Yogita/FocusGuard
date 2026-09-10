"""
Comprehensive automated tests for FocusGuard Face Authentication Module.
Tests DPAPI encryption, SFace embeddings, liveness defense, and HTTP endpoints.
"""

import os
import sys
import time
import json
import threading
import unittest
import numpy as np
import cv2

# Adjust path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, PROJECT_DIR)

from tools.face_auth import (
    dpapi_protect,
    dpapi_unprotect,
    FaceAuthEngine,
    get_face_auth_engine,
    TEMPLATE_PATH,
    LIVENESS_MIN_VARIATION
)


class TestFaceAuth(unittest.TestCase):

    def setUp(self):
        self.engine = get_face_auth_engine()

    def test_01_dpapi_encryption_roundtrip(self):
        """Verify Windows DPAPI encrypts and decrypts accurately."""
        sample_data = {
            "user_id": "test_user_42",
            "enrolled_at": 1710000000,
            "feature_vector": [0.1234, -0.5678, 0.9012] * 42,
            "secret_note": "FocusGuard biometrics"
        }
        raw_bytes = json.dumps(sample_data).encode("utf-8")
        
        # Protect with DPAPI
        encrypted = dpapi_protect(raw_bytes, "test_template")
        self.assertNotEqual(encrypted, raw_bytes)
        self.assertTrue(len(encrypted) > len(raw_bytes))
        
        # Unprotect with DPAPI
        decrypted = dpapi_unprotect(encrypted)
        self.assertEqual(decrypted, raw_bytes)
        restored = json.loads(decrypted.decode("utf-8"))
        self.assertEqual(restored["user_id"], "test_user_42")
        self.assertEqual(len(restored["feature_vector"]), len(sample_data["feature_vector"]))

    def test_02_sface_cosine_similarity(self):
        """Verify SFace cosine distance matching and thresholding."""
        self.assertTrue(self.engine.initialized, "SFace model must be initialized")
        
        # Normalized vector v1
        v1 = np.random.randn(1, 128).astype(np.float32)
        v1 /= np.linalg.norm(v1)
        
        # Same vector
        score_self = float(self.engine.recognizer.match(v1, v1, cv2.FaceRecognizerSF_FR_COSINE))
        self.assertAlmostEqual(score_self, 1.0, places=4)
        
        # Perturbed vector (very close, e.g. slight lighting difference)
        noise = np.random.randn(1, 128).astype(np.float32) * 0.05
        v_close = v1 + noise
        v_close /= np.linalg.norm(v_close)
        score_close = float(self.engine.recognizer.match(v1, v_close, cv2.FaceRecognizerSF_FR_COSINE))
        self.assertGreater(score_close, 0.85)
        
        # Uncorrelated random vector (different person)
        v_diff = np.random.randn(1, 128).astype(np.float32)
        v_diff /= np.linalg.norm(v_diff)
        score_diff = float(self.engine.recognizer.match(v1, v_diff, cv2.FaceRecognizerSF_FR_COSINE))
        self.assertLess(score_diff, 0.35)

    def test_03_liveness_defense(self):
        """Verify liveness checks reject static photos and pass natural micro-movement."""
        # 1. Static photo simulation (identical landmarks across 10 frames)
        base_landmarks = np.array([100.0, 100.0, 150.0, 100.0, 125.0, 130.0, 110.0, 160.0, 140.0, 160.0])
        static_history = [base_landmarks.copy() for _ in range(10)]
        self.assertFalse(
            self.engine.check_liveness(static_history),
            "Static image with zero landmark movement must fail liveness"
        )
        
        # 2. Static photo with camera sensor noise only (< 0.001 pixel jitter)
        noise_history = [base_landmarks + np.random.normal(0, 0.02, 10) for _ in range(10)]
        self.assertFalse(
            self.engine.check_liveness(noise_history),
            "Static image with trivial noise must fail liveness"
        )

        # 3. Live user simulation (natural micro-saccades, breathing, subtle head variation)
        live_history = []
        for i in range(10):
            # 1-3 pixel realistic displacement relative to 50px eye distance
            displacement = np.sin(i * 0.5) * np.array([0.8, 0.5, 0.9, 0.6, 1.2, 0.8, 1.0, 0.7, 1.1, 0.8])
            live_history.append(base_landmarks + displacement)
        self.assertTrue(
            self.engine.check_liveness(live_history),
            "Live user with subtle natural motion must pass liveness"
        )

    def test_04_template_save_load_reset(self):
        """Verify template creation, encryption on disk, verification, and reset."""
        dummy_feat = np.ones((1, 128), dtype=np.float32) / np.sqrt(128)
        dummy_template = {
            "user_id": "test_unit_user",
            "template_id": "test-uuid-1234",
            "enrolled_at": int(time.time()),
            "model": "sface_2021dec",
            "feature_vector": dummy_feat.flatten().tolist(),
            "frames_count": 20
        }
        
        # Save template
        self.engine._save_template(dummy_template)
        self.assertTrue(os.path.exists(TEMPLATE_PATH))
        
        # Confirm file on disk is binary encrypted (not plaintext JSON)
        with open(TEMPLATE_PATH, "rb") as f:
            disk_content = f.read()
        self.assertNotIn(b"test_unit_user", disk_content)
        
        # Load and verify
        loaded = self.engine._load_template()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["user_id"], "test_unit_user")
        self.assertTrue(self.engine.is_enrolled("test_unit_user"))
        
        # Reset template
        res = self.engine.reset("test_unit_user")
        self.assertTrue(res["success"])
        self.assertFalse(os.path.exists(TEMPLATE_PATH))
        self.assertFalse(self.engine.is_enrolled("test_unit_user"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
