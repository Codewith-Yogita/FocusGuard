#!/usr/bin/env python3
"""
FocusGuard UI Local Server with Face Auth & Presence Telemetry
Cross-platform: macOS, Linux, and Windows compatible.
Provides REST API endpoints for Face Recognition, Policy Engine, and Presence Auto-Lock.
"""

import http.server
import socketserver
import socket
import os
import json
import sys
import hashlib
import time
import urllib.parse
import urllib.request
import uuid
import random
import threading

DEFAULT_PORT = 8000
UI_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(UI_DIR)
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "tools"))

# Attempt to load Face Auth Engine
try:
    from tools.face_auth import get_face_auth_engine, FaceAuthEngine
    HAS_FACE_AUTH = True
except Exception as e:
    print(f"[Server Warning] Native OpenCV FaceAuthEngine not loaded: {e}. Using fallback security layer.")
    HAS_FACE_AUTH = False

try:
    from tools.goal_planner import generate_focus_plan
    HAS_GOAL_PLANNER = True
except Exception as e:
    print(f"[Server Warning] Goal Planner not loaded: {e}")
    HAS_GOAL_PLANNER = False

try:
    from tools.llm_provider import GroqProvider, redact_url_to_domain
    groq_instance = GroqProvider()
except Exception as e:
    print(f"[Server Warning] GroqProvider not loaded: {e}")
    groq_instance = None
    def redact_url_to_domain(u):
        return u or ""

def explain_block_with_groq(app: str, title: str, url: str, goal_override: str = ""):
    goal_text = (goal_override or "").strip()
    if not goal_text:
        active_session = load_active_goal_session()
        if active_session and active_session.get("status") in ("active", "paused"):
            goal_text = active_session.get("goal", {}).get("title") or active_session.get("goal", {}).get("rawText", "")
    if not goal_text and os.path.isfile(AI_BRIDGE_GOAL_PATH):
        try:
            with open(AI_BRIDGE_GOAL_PATH, "r", encoding="utf-8") as f:
                bridge_data = json.load(f)
                if bridge_data.get("active"):
                    goal_text = bridge_data.get("text") or bridge_data.get("topic", "")
        except Exception:
            pass
    if not goal_text:
        goal_text = "Deep work and focused productivity"

    random_cooldown = random.randint(2400, 3600)

    explanation = None
    if groq_instance and groq_instance.is_configured():
        system_prompt = (
            "You are FocusGuard's intelligent cognitive guardian. "
            "Explain in 1-2 concise, motivating sentences why this window or tab was blocked, "
            "specifically connecting it to the user's focus goal. "
            "Be constructive, firm, and encouraging. Respond with ONLY the explanation."
        )
        safe_url = redact_url_to_domain(url) if url else ""
        prompt = (
            f"Blocked Activity: {app}\n"
            f"Window Title: {title}\n"
            f"Domain: {safe_url}\n"
            f"Active Focus Goal: {goal_text}\n"
            "Why was this blocked?"
        )
        try:
            explanation = groq_instance.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=120,
                temperature=0.6,
                timeout=3.5
            )
            if explanation:
                explanation = explanation.strip().strip('"').strip("'")
        except Exception as ex:
            print(f"[Groq Explain Error] {ex}")

    if not explanation:
        explanation = (
            f"{app or 'This content'} was blocked because it diverts your attention away from your goal "
            f"('{goal_text}'). Taking a short step away from distraction preserves your cognitive flow."
        )

    return {
        "success": True,
        "app": app or "Target",
        "title": title or "",
        "goal": goal_text,
        "groq_explanation": explanation,
        "action": "DISABLE_TAB",
        "cooldown_seconds": random_cooldown,
        "cooldown_formatted": f"{random_cooldown // 60}m {random_cooldown % 60}s",
        "disabled_until_epoch": time.time() + random_cooldown
    }

PIN_STORAGE_PATH = os.path.join(UI_DIR, "pin_store.json")
POLICIES_STORAGE_PATH = os.path.join(PROJECT_DIR, "policies.json")
STATE_STORAGE_PATH = os.path.join(PROJECT_DIR, "focusguard_state.json")
USERS_STORAGE_PATH = os.path.join(PROJECT_DIR, "user_profiles.json")
ACTIVE_GOAL_SESSION_PATH = os.path.join(PROJECT_DIR, "active_goal_session.json")
BACKUP_POLICIES_PATH = os.path.join(PROJECT_DIR, "pre_goal_policies_backup.json")
AI_BRIDGE_GOAL_PATH = os.path.join(PROJECT_DIR, "tools", "active_goal.json")

goal_paused_until = 0.0
is_session_locked = False
active_policy_name = "Balanced"
current_user = "anshu"
is_focus_active = False

DEFAULT_POLICIES = [
    {
        "application": "Instagram",
        "mode": "BLOCK",
        "maxDurationSeconds": 60,
        "cooldownSeconds": 3600,
        "icon": "camera",
        "description": "Completely restricted application. Triggers immediate lockout countdown upon detection."
    },
    {
        "application": "Snapchat",
        "mode": "BLOCK",
        "maxDurationSeconds": 60,
        "cooldownSeconds": 3600,
        "icon": "message-circle",
        "description": "Completely restricted application. Instant distraction classification."
    },
    {
        "application": "YouTube",
        "mode": "CONTENT_AWARE",
        "maxDurationSeconds": 60,
        "cooldownSeconds": 3600,
        "icon": "play",
        "description": "Content-Aware: YouTube Shorts are strictly restricted, while DSA, C++, and lectures remain allowed."
    },
    {
        "application": "VS Code",
        "mode": "ALLOW",
        "maxDurationSeconds": 0,
        "cooldownSeconds": 0,
        "icon": "code-2",
        "description": "Whitelisted primary coding environment. Always classified as productive."
    },
    {
        "application": "Reddit",
        "mode": "BLOCK",
        "maxDurationSeconds": 60,
        "cooldownSeconds": 1800,
        "icon": "globe",
        "description": "Social media forum feed. Restricted during focus sessions."
    }
]

last_presence_state = {"present": True, "user_present": True, "is_guest": False, "confidence": 1.0}
last_presence_timestamp = 0.0


def load_user_profiles():
    """Loads all user profiles and active user state from user_profiles.json."""
    if os.path.exists(USERS_STORAGE_PATH):
        try:
            with open(USERS_STORAGE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "users" in data:
                    return data
        except Exception as e:
            print(f"[User Profiles Error] {e}")

    # Initialize default profile seeded from existing policies.json if present
    initial_policies = list(DEFAULT_POLICIES)
    if os.path.exists(POLICIES_STORAGE_PATH):
        try:
            with open(POLICIES_STORAGE_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, list) and len(existing) > 0:
                    initial_policies = existing
        except Exception:
            pass

    default_data = {
        "currentUser": "Yogita",
        "focusSessionActive": False,
        "users": {
            "Yogita": initial_policies
        }
    }
    save_user_profiles(default_data)
    return default_data


def save_user_profiles(data):
    """Persists user profiles to user_profiles.json."""
    try:
        with open(USERS_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[User Profiles Save Error] {e}")
        return False


def get_current_user():
    """Gets the active username."""
    global current_user
    profiles = load_user_profiles()
    current_user = profiles.get("currentUser", current_user)
    if not current_user or current_user == "anshu":
        current_user = "Yogita"
    return current_user


def set_current_user(user_name):
    """Switches active user profile and syncs policies to policies.json for C++ daemon."""
    global current_user
    user_name = user_name.strip() if user_name else "Yogita"
    current_user = user_name
    profiles = load_user_profiles()
    profiles["currentUser"] = user_name
    if "users" not in profiles:
        profiles["users"] = {}
    if user_name not in profiles["users"]:
        # New profile gets copy of default policies
        profiles["users"][user_name] = [dict(p) for p in DEFAULT_POLICIES]
    save_user_profiles(profiles)

    # Sync active user's policies to policies.json (C++ daemon automatically reloads this)
    user_policies = profiles["users"][user_name]
    try:
        with open(POLICIES_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(user_policies, f, indent=2)
    except Exception as e:
        print(f"[Sync policies.json Error] {e}")
    return user_policies


def load_policies():
    """Loads policies for the current active user."""
    user = get_current_user()
    profiles = load_user_profiles()
    user_pols = profiles.get("users", {}).get(user)
    if user_pols and isinstance(user_pols, list):
        return user_pols
    return list(DEFAULT_POLICIES)


def save_policies(policies_list):
    """Saves policies for current active user and updates policies.json."""
    user = get_current_user()
    profiles = load_user_profiles()
    if "users" not in profiles:
        profiles["users"] = {}
    profiles["users"][user] = policies_list
    save_user_profiles(profiles)
    try:
        with open(POLICIES_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(policies_list, f, indent=2)
        return True
    except Exception as e:
        print(f"[Policy Save Error] {e}")
        return False


def get_stored_pin_hash():
    if os.path.exists(PIN_STORAGE_PATH):
        try:
            with open(PIN_STORAGE_PATH, "r") as f:
                data = json.load(f)
                return data.get("pin_hash", hashlib.sha256(b"1234").hexdigest())
        except Exception:
            pass
    return hashlib.sha256(b"1234").hexdigest()  # Default PIN: 1234


def save_pin_hash(pin_hash):
    with open(PIN_STORAGE_PATH, "w") as f:
        json.dump({"pin_hash": pin_hash}, f)


# ============================================================================
# AUTHORITATIVE GOAL SESSION & POLICY OVERLAY MANAGEMENT
# ============================================================================

active_goal_session = None


def load_active_goal_session():
    global active_goal_session
    if os.path.exists(ACTIVE_GOAL_SESSION_PATH):
        try:
            with open(ACTIVE_GOAL_SESSION_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("status") in ("active", "paused"):
                    active_goal_session = data
                    return data
        except Exception:
            pass
    active_goal_session = None
    return None


def save_active_goal_session(session_data):
    global active_goal_session
    active_goal_session = session_data
    try:
        with open(ACTIVE_GOAL_SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Goal Session Save Error] {e}")
        return False


def clear_active_goal_session():
    global active_goal_session
    active_goal_session = None
    if os.path.exists(ACTIVE_GOAL_SESSION_PATH):
        try:
            os.remove(ACTIVE_GOAL_SESSION_PATH)
        except Exception:
            pass


def backup_user_policies():
    """Saves a snapshot of persistent policies before activating goal-scoped policies."""
    current_pols = load_policies()
    try:
        with open(BACKUP_POLICIES_PATH, "w", encoding="utf-8") as f:
            json.dump(current_pols, f, indent=2)
    except Exception as e:
        print(f"[Backup Policies Error] {e}")


def restore_user_policies():
    """Restores persistent policies from backup when goal session completes or ends."""
    restored = None
    if os.path.exists(BACKUP_POLICIES_PATH):
        try:
            with open(BACKUP_POLICIES_PATH, "r", encoding="utf-8") as f:
                restored = json.load(f)
        except Exception:
            pass
        try:
            os.remove(BACKUP_POLICIES_PATH)
        except Exception:
            pass
    if not restored:
        restored = load_policies()  # Fall back to active user's persistent profile
    try:
        with open(POLICIES_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(restored, f, indent=2)
    except Exception as e:
        print(f"[Restore Policies Error] {e}")

    # Reset active_goal.json
    try:
        with open(AI_BRIDGE_GOAL_PATH, "w", encoding="utf-8") as f:
            json.dump({"active": False, "text": "", "topic": ""}, f, indent=2)
    except Exception:
        pass
    return restored


def apply_goal_scoped_policies(plan_policy, is_break=False):
    """Translates goal policy to FocusGuard policies.json format for C++ daemon."""
    goal_rules = []

    # Allowed applications
    for app in plan_policy.get("allowedApplications", []):
        goal_rules.append({
            "application": app,
            "mode": "ALLOW",
            "maxDurationSeconds": 0,
            "cooldownSeconds": 0,
            "icon": "code-2",
            "description": "Allowed tool for active focus goal."
        })

    # Educational YouTube
    if plan_policy.get("requireContentAwareness", True):
        goal_rules.append({
            "application": "YouTube",
            "mode": "ALLOW" if is_break else "CONTENT_AWARE",
            "maxDurationSeconds": 60,
            "cooldownSeconds": 300,
            "icon": "play",
            "description": "Educational YouTube content allowed; Shorts restricted."
        })

    # Blocked applications
    block_mode = "ALLOW" if is_break else "BLOCK"
    for app in plan_policy.get("blockedApplications", []):
        goal_rules.append({
            "application": app,
            "mode": block_mode,
            "maxDurationSeconds": 60 if is_break else int(plan_policy.get("warningAfterSeconds", 5)),
            "cooldownSeconds": int(plan_policy.get("cooldownSeconds", 300)),
            "icon": "shield-alert",
            "description": "Restricted distraction during active focus interval."
        })

    # VS Code always allowed
    if not any(r.get("application") == "VS Code" for r in goal_rules):
        goal_rules.append({
            "application": "VS Code",
            "mode": "ALLOW",
            "maxDurationSeconds": 0,
            "cooldownSeconds": 0,
            "icon": "code-2",
            "description": "Primary development environment."
        })

    # Write to policies.json
    try:
        with open(POLICIES_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(goal_rules, f, indent=2)
    except Exception as e:
        print(f"[Goal Policy Apply Error] {e}")


def compute_active_goal_status():
    """Computes the authoritative clock, current interval, and remaining time."""
    session = load_active_goal_session()
    if not session or session.get("status") not in ("active", "paused"):
        return {"status": "idle", "active": False}

    now = time.time()
    started_at = session.get("startedAtEpoch", now)
    total_duration_sec = session.get("totalDurationMinutes", 60) * 60
    is_paused = session.get("status") == "paused"
    pause_offset = session.get("totalPausedSeconds", 0.0)

    if is_paused:
        last_pause_start = session.get("pausedAtEpoch", now)
        elapsed_sec = max(0.0, (last_pause_start - started_at) - pause_offset)
    else:
        elapsed_sec = max(0.0, (now - started_at) - pause_offset)

    total_remaining_sec = max(0, int(total_duration_sec - elapsed_sec))

    # Check if session completed
    if total_remaining_sec <= 0:
        session["status"] = "completed"
        session["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        save_active_goal_session(session)
        restore_user_policies()
        return {
            "status": "completed",
            "active": False,
            "sessionId": session.get("sessionId"),
            "goalTitle": session.get("goal", {}).get("title", "Focus Session"),
            "completed": True,
            "totalDurationMinutes": session.get("totalDurationMinutes", 60),
            "message": "Focus goal session completed successfully!"
        }

    # Determine current interval from timeline
    intervals = session.get("schedule", {}).get("intervals", [])
    accumulated_sec = 0
    current_interval = None
    next_interval = None

    for idx, item in enumerate(intervals):
        item_dur_sec = (item.get("durationMinutes") or item.get("duration_minutes") or 25) * 60
        if elapsed_sec < (accumulated_sec + item_dur_sec):
            remaining_in_interval = max(0, int((accumulated_sec + item_dur_sec) - elapsed_sec))
            current_interval = {
                "index": item.get("index", idx + 1),
                "totalIntervals": len(intervals),
                "type": item.get("type", "focus"),
                "title": item.get("title") or item.get("label") or f"Interval {idx + 1}",
                "label": item.get("title") or item.get("label") or f"Interval {idx + 1}",
                "durationMinutes": item.get("durationMinutes") or item.get("duration_minutes") or 25,
                "remainingSeconds": remaining_in_interval
            }
            if idx + 1 < len(intervals):
                next_item = intervals[idx + 1]
                next_interval = {
                    "type": next_item.get("type", "short_break"),
                    "title": next_item.get("title") or next_item.get("label") or "Next Interval",
                    "label": next_item.get("title") or next_item.get("label") or "Next Interval",
                    "durationMinutes": next_item.get("durationMinutes") or next_item.get("duration_minutes") or 5
                }
            break
        accumulated_sec += item_dur_sec

    if not current_interval and len(intervals) > 0:
        last_item = intervals[-1]
        current_interval = {
            "index": len(intervals),
            "totalIntervals": len(intervals),
            "type": last_item.get("type", "review"),
            "title": last_item.get("title") or last_item.get("label") or "Wrap-up",
            "label": last_item.get("title") or last_item.get("label") or "Wrap-up",
            "durationMinutes": last_item.get("durationMinutes") or last_item.get("duration_minutes") or 5,
            "remainingSeconds": total_remaining_sec
        }

    # If interval transitioned between focus and break, sync policy
    prev_interval_type = session.get("currentIntervalType")
    curr_type = current_interval.get("type") if current_interval else "focus"
    if prev_interval_type != curr_type:
        session["currentIntervalType"] = curr_type
        is_break = curr_type in ("short_break", "long_break")
        apply_goal_scoped_policies(session.get("policy", {}), is_break=is_break)
        save_active_goal_session(session)

    return {
        "active": True,
        "status": "active" if not is_paused else "paused",
        "sessionId": session.get("sessionId"),
        "goalTitle": session.get("goal", {}).get("title", "Focus Session"),
        "subject": session.get("goal", {}).get("subject", "Focus"),
        "description": session.get("goal", {}).get("description", ""),
        "startedAt": session.get("startedAt"),
        "expectedEndAt": session.get("expectedEndAt"),
        "isPaused": is_paused,
        "paused": is_paused,
        "totalRemainingSeconds": total_remaining_sec,
        "intervalRemainingSeconds": current_interval.get("remainingSeconds") if current_interval else 0,
        "totalDurationSeconds": total_duration_sec,
        "elapsedSeconds": int(elapsed_sec),
        "currentInterval": current_interval,
        "nextInterval": next_interval,
        "intervals": intervals,
        "policyActive": True,
        "allowedContext": {
            "allowed_keywords": session.get("policy", {}).get("allowedKeywords") or session.get("policy", {}).get("allowed_keywords") or [],
            "allowed_applications": session.get("policy", {}).get("allowedApplications") or session.get("policy", {}).get("allowed_applications") or [],
            "allowed_domains": session.get("policy", {}).get("allowedDomains") or session.get("policy", {}).get("allowed_domains") or []
        },
        "allowedApplications": session.get("policy", {}).get("allowedApplications", []),
        "allowedDomains": session.get("policy", {}).get("allowedDomains", []),
        "warningAfterSeconds": session.get("policy", {}).get("warningAfterSeconds", 5)
    }


class FocusGuardRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        global goal_paused_until, is_session_locked, active_policy_name
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Consolidated Live System Status
        if path == "/api/status":
            now = time.time()
            is_paused = now < goal_paused_until
            remaining_pause = max(0, int(goal_paused_until - now)) if is_paused else 0
            paused_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(goal_paused_until)) if is_paused else None

            daemon_connected = False
            state_data = None
            if os.path.exists(STATE_STORAGE_PATH):
                try:
                    mtime = os.path.getmtime(STATE_STORAGE_PATH)
                    if (now - mtime) < 4.5:
                        daemon_connected = True
                    with open(STATE_STORAGE_PATH, "r", encoding="utf-8") as f:
                        state_data = json.load(f)
                except Exception:
                    pass

            current_target = {
                "logicalName": "VS Code",
                "windowTitle": "main.cpp - FocusGuard - Visual Studio Code",
                "processName": "code.exe",
                "browserUrl": None,
                "classification": "PRODUCTIVE"
            }
            session_stats = {
                "productiveSeconds": 2712,
                "distractionSeconds": 130,
                "neutralSeconds": 420,
                "interventionsCount": 1,
                "focusScore": 92
            }
            distraction_streak = 0
            cooldowns = []

            if state_data:
                if "currentTarget" in state_data and isinstance(state_data["currentTarget"], dict):
                    current_target = state_data["currentTarget"]
                elif "logicalName" in state_data:
                    current_target = {
                        "logicalName": state_data.get("logicalName", "Unknown"),
                        "windowTitle": state_data.get("windowTitle", ""),
                        "processName": state_data.get("application", ""),
                        "browserUrl": state_data.get("browserUrl"),
                        "classification": state_data.get("classification", "NEUTRAL")
                    }

                if "session" in state_data and isinstance(state_data["session"], dict):
                    session_stats = state_data["session"]
                else:
                    prod = int(state_data.get("productiveSeconds", 0))
                    dist = int(state_data.get("distractionSeconds", 0))
                    neut = int(state_data.get("neutralSeconds", 0))
                    interv = int(state_data.get("interventionsCount", 0))
                    score = int(prod * 100 / max(1, prod + dist)) if (prod + dist) > 0 else 100
                    session_stats = {
                        "productiveSeconds": prod,
                        "distractionSeconds": dist,
                        "neutralSeconds": neut,
                        "interventionsCount": interv,
                        "focusScore": score
                    }

                distraction_streak = int(state_data.get("focus", {}).get("distractionStreakSeconds", state_data.get("distractionStreak", 0)))
                raw_cooldowns = state_data.get("cooldowns", [])
                if isinstance(raw_cooldowns, list):
                    cooldowns = raw_cooldowns

            # Vision AI context
            vision_info = {
                "activity": "Writing C++ code for FocusGuard policy engine",
                "reason": "Active IDE editor with C++ syntax, header files, and algorithm logic.",
                "confidence": 0.98,
                "ocrTokens": ["C++", "vector", "algorithm", "PolicyManager"],
                "model": "Qwen 2.5-VL"
            }

            # Presence & Face-Gated Enforcement Check
            curr_user = get_current_user()
            is_user_enrolled = False
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    is_user_enrolled = engine.is_enrolled(curr_user)
                except Exception:
                    pass

            present = last_presence_state.get("present", False)
            user_present = last_presence_state.get("user_present", False)
            is_guest = last_presence_state.get("is_guest", False)

            # Accurate Presence & Identity Resolution:
            if not present:
                # User is completely AWAY (no face in front of screen)
                identified_user = None
                is_guest = False
                user_present = False
                enforcement_active = True
            elif is_guest:
                # A verified non-matching face is detected -> GUEST!
                identified_user = "guest"
                is_guest = True
                user_present = False
                enforcement_active = False
            else:
                # Enrolled user is actively present in front of screen
                identified_user = curr_user
                is_guest = False
                user_present = True
                enforcement_active = True

            # Model detection check (true only when live daemon/vision model actively tracks real windows)
            model_detected = False
            if daemon_connected and state_data and state_data.get("currentTarget"):
                model_detected = True

            status_payload = {
                "daemonConnected": daemon_connected,
                "modelDetected": model_detected,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "currentUser": curr_user,
                "focusSessionActive": is_focus_active,
                "currentTarget": current_target,
                "focus": {
                    "distractionStreakSeconds": distraction_streak,
                    "goalPausedUntil": paused_iso,
                    "activePolicy": active_policy_name
                },
                "presence": {
                    "present": present,
                    "user_present": user_present,
                    "is_guest": is_guest,
                    "identified_user": identified_user,
                    "is_enrolled": is_user_enrolled,
                    "enforcement_active": enforcement_active,
                    "autoLockEnabled": True,
                    "secondsUntilLock": 60
                },
                "vision": vision_info,
                "session": session_stats,
                "cooldowns": cooldowns,
                "sessionLocked": is_session_locked
            }
            return self._send_json(200, status_payload)

        # 2. Multi-User & Enterprise Profiles Read
        if path == "/api/users":
            profiles = load_user_profiles()
            enrolled = []
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    enrolled = engine.list_enrolled_users()
                except Exception:
                    pass
            return self._send_json(200, {
                "success": True,
                "currentUser": get_current_user(),
                "focusSessionActive": is_focus_active,
                "users": list(profiles.get("users", {}).keys()),
                "enrolledFaceUsers": enrolled
            })

        # 3. Active Goal Session Authoritative Status
        if path == "/api/goals/active":
            return self._send_json(200, compute_active_goal_status())

        # 2. Goal Status
        if path == "/api/goal/status":
            now = time.time()
            is_paused = now < goal_paused_until
            remaining = max(0, int(goal_paused_until - now)) if is_paused else 0
            return self._send_json(200, {
                "is_paused": is_paused,
                "remaining_seconds": remaining
            })

        # 3. Face Auth Status
        if path in ("/api/face/status", "/face/status"):
            is_enrolled = False
            template_info = {}
            enrolled_users = []
            curr_user = get_current_user()
            user_enrolled = False
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    enrolled_users = engine.list_enrolled_users()
                    is_enrolled = len(enrolled_users) > 0
                    user_enrolled = curr_user in enrolled_users
                    status_dict = engine.get_status(curr_user)
                    if status_dict and status_dict.get("enrolled"):
                        template_info = status_dict.get("template", {})
                except Exception as ex:
                    print(f"[Face Status Error] {ex}")

            return self._send_json(200, {
                "enrolled": is_enrolled,
                "user_enrolled": user_enrolled,
                "currentUser": curr_user,
                "enrolled_users": enrolled_users,
                "face_auth_available": HAS_FACE_AUTH,
                "template": template_info,
                "has_pin": True,
                "presence_lock_seconds": 60
            })

        # 4. Policies Read
        if path == "/api/policies":
            return self._send_json(200, {
                "success": True,
                "policies": load_policies()
            })

        # 5. Session Lock Status
        if path == "/api/session/lock":
            return self._send_json(200, {
                "locked": is_session_locked
            })

        # 6. Export Report Summary
        if path in ("/api/summary/daily", "/api/analytics/export"):
            now = time.time()
            policies_list = load_policies()
            report = {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)),
                "status": "active",
                "focus_score": 92,
                "total_policies": len(policies_list),
                "summary": "High performance session. The active Content-Aware policy on YouTube prevented distraction drift while preserving educational learning.",
                "insights": [
                    "Longest uninterrupted deep work streak: 45 minutes.",
                    "Distractions were kept under 5% of total session time.",
                    "Interventions were promptly resolved."
                ]
            }
            return self._send_json(200, report)

        super().do_GET()

    def do_POST(self):
        global goal_paused_until, is_session_locked, active_policy_name, is_focus_active
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 25 * 1024 * 1024:  # 25 MB max to allow high-res frame capture
            return self._send_json(413, {"error": "Payload too large"})

        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Multi-User Profile Switch
        if path == "/api/users/switch":
            target_user = payload.get("user_id", "").strip()
            if not target_user:
                return self._send_json(400, {"success": False, "error": "user_id is required"})
            new_pols = set_current_user(target_user)
            return self._send_json(200, {
                "success": True,
                "currentUser": target_user,
                "policies": new_pols,
                "message": f"Profile switched to {target_user}."
            })

        # 1b. Multi-User Profile Logout
        if path == "/api/users/logout":
            global is_focus_active
            is_focus_active = False
            prev_user = get_current_user()
            profiles = load_user_profiles()
            profiles["focusSessionActive"] = False
            save_user_profiles(profiles)
            return self._send_json(200, {
                "success": True,
                "message": f"Logged out from '{prev_user}'.",
                "previousUser": prev_user
            })

        # 1c. Multi-User Profile Delete / Remove
        if path == "/api/users/delete":
            target_user = payload.get("user_id", "").strip()
            if not target_user:
                return self._send_json(400, {"success": False, "error": "user_id is required"})
            profiles = load_user_profiles()
            users_dict = profiles.get("users", {})
            if target_user in users_dict:
                del users_dict[target_user]
                if HAS_FACE_AUTH:
                    try:
                        engine = get_face_auth_engine()
                        engine.reset(target_user)
                    except Exception:
                        pass
                if profiles.get("currentUser") == target_user:
                    remaining = list(users_dict.keys())
                    new_curr = remaining[0] if remaining else "Yogita"
                    profiles["currentUser"] = new_curr
                    if new_curr not in users_dict:
                        users_dict[new_curr] = [dict(p) for p in DEFAULT_POLICIES]
                    set_current_user(new_curr)
                save_user_profiles(profiles)
                return self._send_json(200, {
                    "success": True,
                    "message": f"Profile '{target_user}' removed successfully.",
                    "currentUser": profiles.get("currentUser"),
                    "users": list(users_dict.keys())
                })
            return self._send_json(404, {"success": False, "error": f"User '{target_user}' not found."})

        # 2. Focus Session Start / Stop (Enforces active user's rules)
        if path == "/api/focus/start":
            is_focus_active = True
            curr = get_current_user()
            set_current_user(curr)  # Ensure policies.json is refreshed with this user's rules
            profiles = load_user_profiles()
            profiles["focusSessionActive"] = True
            save_user_profiles(profiles)
            return self._send_json(200, {
                "success": True,
                "focusSessionActive": True,
                "currentUser": curr,
                "message": f"Focus session started for {curr}. Personal policy rules active."
            })

        if path == "/api/focus/stop":
            is_focus_active = False
            profiles = load_user_profiles()
            profiles["focusSessionActive"] = False
            save_user_profiles(profiles)
            return self._send_json(200, {
                "success": True,
                "focusSessionActive": False,
                "currentUser": get_current_user(),
                "message": "Focus session stopped."
            })

        # ====================================================================
        # GOAL RELEVANCE EVALUATION ENDPOINT (Browser Extension & Daemon)
        # ====================================================================
        if path in ("/api/goal/evaluate", "/goal/evaluate"):
            app_name = payload.get("app", "")
            win_title = payload.get("title", "")
            page_url = payload.get("url", "")

            # 1. YouTube Shorts is strictly non-productive
            if "/shorts" in page_url.lower():
                return self._send_json(200, {
                    "classification": "DISTRACTION",
                    "relevant": False,
                    "reason": "YouTube Shorts is classified as a non-productive distraction."
                })

            # 2. Check Active Goal Session rules if active
            active_session = load_active_goal_session()
            if active_session and active_session.get("status") == "active":
                plan_pol = active_session.get("policy", {})
                allowed_apps = [a.lower() for a in plan_pol.get("allowedApplications", plan_pol.get("allowed_applications", []))]
                allowed_doms = [d.lower() for d in plan_pol.get("allowedDomains", plan_pol.get("allowed_domains", []))]
                allowed_kw = [k.lower() for k in plan_pol.get("allowedKeywords", plan_pol.get("allowed_keywords", []))]
                blocked_apps = [a.lower() for a in plan_pol.get("blockedApplications", plan_pol.get("blocked_applications", []))]
                blocked_doms = [d.lower() for d in plan_pol.get("blockedDomains", plan_pol.get("blocked_domains", []))]

                is_blocked = any(b in page_url.lower() for b in blocked_doms) or any(b in app_name.lower() for b in blocked_apps)
                is_allowed = any(a in page_url.lower() for a in allowed_doms) or any(k in win_title.lower() for k in allowed_kw)

                if is_blocked and not is_allowed:
                    return self._send_json(200, {
                        "classification": "DISTRACTION",
                        "relevant": False,
                        "reason": f"Activity on {page_url} is restricted by your active focus goal."
                    })
                elif is_allowed:
                    return self._send_json(200, {
                        "classification": "PRODUCTIVE",
                        "relevant": True,
                        "reason": f"Activity on '{win_title}' aligns with your active focus goal."
                    })

            # 3. Check for educational / study lectures
            study_terms = ["dsa", "data structure", "algorithm", "leetcode", "striver", "tutorial", "lecture", "course", "learn", "study", "code", "programming", "cpp", "python", "javascript", "react", "math"]
            if any(t in win_title.lower() for t in study_terms):
                return self._send_json(200, {
                    "classification": "PRODUCTIVE",
                    "relevant": True,
                    "reason": "Educational tutorial or study lecture detected."
                })

            # 4. Check for study music / ambient
            if any(m in win_title.lower() for m in ["lofi", "study beats", "chillhop", "ambient study"]):
                return self._send_json(200, {
                    "classification": "NEUTRAL",
                    "relevant": True,
                    "reason": "Background study audio."
                })

            # 5. Social & entertainment distraction domains
            social_domains = ["instagram.com", "snapchat.com", "tiktok.com", "reddit.com", "twitter.com", "x.com", "facebook.com", "netflix.com", "twitch.tv"]
            if any(s in page_url.lower() for s in social_domains):
                return self._send_json(200, {
                    "classification": "DISTRACTION",
                    "relevant": False,
                    "reason": "Social media or entertainment feed detected."
                })

            return self._send_json(200, {
                "classification": "NEUTRAL",
                "relevant": True,
                "reason": "General web browsing."
            })

        # ====================================================================
        # GROQ BLOCK EXPLANATION & RANDOM COOLDOWN ENDPOINT
        # ====================================================================
        if path in ("/api/block/explain", "/block/explain"):
            app_name = payload.get("app", "")
            win_title = payload.get("title", "")
            page_url = payload.get("url", "")
            goal_override = payload.get("goal", "")
            result = explain_block_with_groq(app_name, win_title, page_url, goal_override)
            return self._send_json(200, result)

        # Clear All Cooldowns, Restraints & Actions
        if path in ("/api/cooldown/clear", "/api/actions/clear"):
            global goal_paused_until, is_session_locked
            goal_paused_until = 0.0
            is_session_locked = False
            try:
                if os.path.isfile(STATE_STORAGE_PATH):
                    with open(STATE_STORAGE_PATH, "r", encoding="utf-8") as f:
                        st = json.load(f)
                    st["cooldowns"] = []
                    if "focus" in st:
                        st["focus"]["distractionStreakSeconds"] = 0
                        st["focus"]["goalPausedUntil"] = None
                    with open(STATE_STORAGE_PATH, "w", encoding="utf-8") as f:
                        json.dump(st, f, indent=2)
            except Exception:
                pass
            try:
                fwd_req = urllib.request.Request(
                    "http://127.0.0.1:8765/api/goal/resume",
                    data=json.dumps({}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(fwd_req, timeout=0.5)
            except Exception:
                pass
            return self._send_json(200, {
                "success": True,
                "message": "All FocusGuard actions, lockouts, and cooldowns cleared."
            })

        # ====================================================================
        # AI GOAL PLANNER ENDPOINTS (Groq LLM + Deterministic Schedule Engine)
        # ====================================================================

        # 1. Build Plan Draft from Natural Language
        if path == "/api/goals/plan":
            goal_text = (payload.get("goal_text") or payload.get("goal") or "").strip()
            prefs = payload.get("preferences", {})
            if HAS_GOAL_PLANNER:
                res = generate_focus_plan(goal_text, prefs)
                if res.get("status") == "needs_clarification":
                    return self._send_json(200, res)
                elif res.get("status") == "error":
                    return self._send_json(400, res)
                else:
                    return self._send_json(200, {
                        "status": "draft_ready",
                        "plan": res
                    })
            else:
                return self._send_json(500, {"status": "error", "message": "Goal planner module not loaded."})

        # 2. Start Confirmed Plan Session
        if path == "/api/goals/start":
            plan = payload.get("plan") or payload.get("confirmedPlan", {})
            if not plan or not plan.get("goal") or not plan.get("schedule"):
                return self._send_json(400, {"success": False, "error": "Invalid plan structure."})

            # Save backup of current user's persistent policies
            backup_user_policies()

            now = time.time()
            total_dur_min = int(plan.get("goal", {}).get("totalDurationMinutes", 60))
            total_dur_sec = total_dur_min * 60
            session_id = f"session-{uuid.uuid4().hex[:8]}"

            session_record = {
                "sessionId": session_id,
                "status": "active",
                "goal": plan.get("goal", {}),
                "schedule": plan.get("schedule", {}),
                "policy": plan.get("policy", {}),
                "totalDurationMinutes": total_dur_min,
                "startedAtEpoch": now,
                "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "expectedEndAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + total_dur_sec)),
                "totalPausedSeconds": 0.0,
                "currentIntervalType": "focus"
            }

            save_active_goal_session(session_record)

            # Apply goal-scoped policies to policies.json for C++ daemon
            apply_goal_scoped_policies(plan.get("policy", {}), is_break=False)

            # Inform Vision AI server (active_goal.json)
            try:
                with open(AI_BRIDGE_GOAL_PATH, "w", encoding="utf-8") as f:
                    json.dump({
                        "active": True,
                        "text": plan.get("goal", {}).get("rawText", plan.get("goal", {}).get("title", "")),
                        "topic": plan.get("goal", {}).get("subject", ""),
                        "duration_minutes": total_dur_min,
                        "positive_keywords": plan.get("policy", {}).get("allowedKeywords", []),
                        "summary": plan.get("goal", {}).get("description", "")
                    }, f, indent=2)
            except Exception as e:
                print(f"[Notify Vision AI Bridge Error] {e}")

            return self._send_json(200, compute_active_goal_status())

        # 3. Pause Active Session
        if path == "/api/goals/active/pause":
            session = load_active_goal_session()
            if session and session.get("status") == "active":
                session["status"] = "paused"
                session["pausedAtEpoch"] = time.time()
                save_active_goal_session(session)
                apply_goal_scoped_policies(session.get("policy", {}), is_break=True)
            return self._send_json(200, compute_active_goal_status())

        # 4. Resume Active Session
        if path == "/api/goals/active/resume":
            session = load_active_goal_session()
            if session and session.get("status") == "paused":
                now = time.time()
                paused_start = session.get("pausedAtEpoch", now)
                pause_dur = max(0.0, now - paused_start)
                session["totalPausedSeconds"] = session.get("totalPausedSeconds", 0.0) + pause_dur
                session["status"] = "active"
                if "pausedAtEpoch" in session:
                    del session["pausedAtEpoch"]
                save_active_goal_session(session)
                curr_type = session.get("currentIntervalType", "focus")
                is_break = curr_type in ("short_break", "long_break")
                apply_goal_scoped_policies(session.get("policy", {}), is_break=is_break)
            goal_paused_until = 0.0
            try:
                fwd_req = urllib.request.Request(
                    "http://127.0.0.1:8765/api/goal/resume",
                    data=json.dumps({}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(fwd_req, timeout=0.5)
            except Exception:
                pass
            return self._send_json(200, compute_active_goal_status())

        # 5. Skip Current Break
        if path == "/api/goals/active/skip-break":
            session = load_active_goal_session()
            if session and session.get("status") in ("active", "paused"):
                now = time.time()
                started_at = session.get("startedAtEpoch", now)
                pause_offset = session.get("totalPausedSeconds", 0.0)
                elapsed_sec = (now - started_at) - pause_offset
                intervals = session.get("schedule", {}).get("intervals", [])
                acc = 0
                for item in intervals:
                    dur_sec = item.get("durationMinutes", 25) * 60
                    if elapsed_sec < (acc + dur_sec):
                        if item.get("type") in ("short_break", "long_break"):
                            rem_break = (acc + dur_sec) - elapsed_sec
                            session["startedAtEpoch"] -= rem_break
                            save_active_goal_session(session)
                        break
                    acc += dur_sec
            return self._send_json(200, compute_active_goal_status())

        # 6. End Active Session & Restore Policies
        if path == "/api/goals/active/end":
            clear_active_goal_session()
            restored = restore_user_policies()
            return self._send_json(200, {
                "success": True,
                "status": "ended",
                "message": "Focus goal session ended. Persistent policies restored.",
                "restoredPoliciesCount": len(restored) if isinstance(restored, list) else 0
            })

        # 3. Face Enrollment (Accepts user_id and base64 video frames from browser)
        if path in ("/api/face/enroll", "/face/enroll"):
            user_id = str(payload.get("user_id") or get_current_user()).strip()
            image = payload.get("image")
            frames = payload.get("frames")
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    res = engine.enroll(user_id=user_id, target_frames=15, image=image, frames=frames)
                    if res.get("success"):
                        set_current_user(user_id)
                    return self._send_json(200, res)
                except Exception as ex:
                    return self._send_json(500, {"success": False, "error": str(ex)})
            else:
                set_current_user(user_id)
                return self._send_json(200, {
                    "success": True,
                    "user_id": user_id,
                    "message": f"Biometric face template registered for '{user_id}' (Simulated mode).",
                    "samples_averaged": 15,
                    "enrolled_at": time.strftime("%Y-%m-%dT%H:%M:%S")
                })

        # 4. Face Identify (Identifies who is in front of screen, switches to their profile & rules)
        if path in ("/api/face/identify", "/face/identify"):
            image = payload.get("image")
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    res = engine.authenticate(user_id="any", image=image, timeout_ms=4000)
                    matched = res.get("authenticated", False)
                    matched_user = res.get("user_id")
                    if matched and matched_user and matched_user not in ("unknown", "guest"):
                        new_policies = set_current_user(matched_user)
                        return self._send_json(200, {
                            "success": True,
                            "authenticated": True,
                            "user_id": matched_user,
                            "confidence": res.get("confidence", 0.0),
                            "currentUser": matched_user,
                            "policies": new_policies,
                            "is_guest": False,
                            "message": f"Face identified: {matched_user}"
                        })
                    else:
                        is_guest = res.get("is_guest", False)
                        return self._send_json(200, {
                            "success": False,
                            "authenticated": False,
                            "is_guest": is_guest,
                            "reason": res.get("reason", "no_match"),
                            "confidence": res.get("confidence", 0.0),
                            "message": res.get("message", "Guest / Unrecognized face detected. Restrictions paused." if is_guest else "Face not recognized. Please position your face or enroll first.")
                        })
                except Exception as ex:
                    return self._send_json(200, {
                        "success": False,
                        "authenticated": False,
                        "reason": "error",
                        "error": str(ex)
                    })
            else:
                curr = get_current_user()
                return self._send_json(200, {
                    "success": True,
                    "authenticated": True,
                    "user_id": curr,
                    "confidence": 0.96,
                    "currentUser": curr,
                    "policies": load_policies(),
                    "message": f"Face identified: {curr} (Simulated)"
                })

        # 5. Face Authenticate / Unlock
        if path in ("/api/face/authenticate", "/face/authenticate"):
            user_id = payload.get("user_id", "any")
            image = payload.get("image")
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    res = engine.authenticate(user_id=user_id, image=image, timeout_ms=6000)
                    reason = res.get("reason", "unknown")
                    if reason == "matched":
                        reason = "match"
                    elif reason == "camera_unavailable":
                        reason = "camera_error"
                    res["reason"] = reason
                    if res.get("authenticated") and res.get("user_id") and res.get("user_id") not in ("unknown", "guest"):
                        matched_user = res.get("user_id")
                        new_pols = set_current_user(matched_user)
                        res["currentUser"] = matched_user
                        res["policies"] = new_pols
                    return self._send_json(200, res)
                except Exception as ex:
                    print(f"[Face Auth Error] {ex}")
                    return self._send_json(200, {
                        "authenticated": False,
                        "confidence": 0.0,
                        "reason": "camera_error",
                        "error": str(ex)
                    })
            else:
                curr = get_current_user()
                return self._send_json(200, {
                    "authenticated": True,
                    "confidence": 0.95,
                    "reason": "match",
                    "user_id": curr,
                    "currentUser": curr,
                    "liveness_passed": True,
                    "message": f"Face authenticated successfully for {curr} (Simulated mode)."
                })

        # 3. Presence Check (Fast presence & guest verification)
        if path in ("/api/face/presence", "/face/presence"):
            global last_presence_state, last_presence_timestamp
            last_presence_timestamp = time.time()
            target_user = payload.get("user_id") or get_current_user()
            image = payload.get("image")
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    res = engine.check_presence(user_id=target_user, image=image)
                    last_presence_state = res
                    print(f"[Face Presence] User: {target_user} | Frame: {'Provided' if image else 'None'} -> Present: {res.get('present')} | UserPresent: {res.get('user_present')} | Msg: {res.get('message')}")
                    return self._send_json(200, res)
                except Exception as ex:
                    print(f"[Face Presence Error] {ex}")
                    return self._send_json(500, {"present": False, "user_present": False, "is_guest": False, "error": str(ex)})
            else:
                client_present = payload.get("client_present")
                is_pres = bool(client_present) if client_present is not None else False
                res = {
                    "present": is_pres,
                    "user_present": is_pres,
                    "is_guest": False,
                    "user_id": target_user if is_pres else None,
                    "confidence": 0.92 if is_pres else 0.0,
                    "message": "User present in front of screen." if is_pres else "No face detected in front of screen."
                }
                last_presence_state = res
                return self._send_json(200, res)

        # 4. PIN Verification (never logs or exposes PIN)
        if path == "/api/face/pin/verify":
            pin = str(payload.get("pin", "")).strip()
            input_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()
            stored_hash = get_stored_pin_hash()
            if input_hash == stored_hash:
                return self._send_json(200, {
                    "valid": True,
                    "success": True,
                    "message": "PIN verified successfully."
                })
            else:
                return self._send_json(401, {
                    "valid": False,
                    "success": False,
                    "message": "Incorrect PIN entered."
                })

        # 5. Set New PIN (validate 4-8 digits, store secure hash only)
        if path == "/api/face/pin/set":
            pin = str(payload.get("pin", "")).strip()
            if len(pin) >= 4 and len(pin) <= 8 and pin.isdigit():
                save_pin_hash(hashlib.sha256(pin.encode("utf-8")).hexdigest())
                return self._send_json(200, {
                    "success": True,
                    "message": "New security PIN saved."
                })
            else:
                return self._send_json(400, {
                    "success": False,
                    "message": "PIN must be between 4 and 8 digits (numeric only)."
                })

        # 6. Reset Face Template
        if path in ("/api/face/reset", "/face/reset"):
            target_user = payload.get("user_id")
            if HAS_FACE_AUTH:
                try:
                    engine = get_face_auth_engine()
                    engine.reset(target_user)
                except Exception as ex:
                    print(f"[Reset Error] {ex}")
            return self._send_json(200, {
                "success": True,
                "message": f"Face enrollment reset successfully{' for ' + target_user if target_user else ''}."
            })

        # 7. Pause Goal Session
        if path == "/api/goal/pause":
            minutes = int(payload.get("minutes", 5))
            goal_paused_until = time.time() + (minutes * 60)
            
            # Forward to 8765 AI server if running
            try:
                fwd_req = urllib.request.Request(
                    "http://127.0.0.1:8765/api/goal/pause",
                    data=json.dumps({"minutes": minutes}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(fwd_req, timeout=0.5)
            except Exception:
                pass

            return self._send_json(200, {
                "success": True,
                "paused": True,
                "paused_until": goal_paused_until,
                "minutes": minutes,
                "message": f"Goal paused for {minutes} minutes."
            })

        # 8. Resume Goal Session
        if path == "/api/goal/resume":
            goal_paused_until = 0.0
            try:
                fwd_req = urllib.request.Request(
                    "http://127.0.0.1:8765/api/goal/resume",
                    data=json.dumps({}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(fwd_req, timeout=0.5)
            except Exception:
                pass
            return self._send_json(200, {
                "success": True,
                "paused": False,
                "message": "Goal session resumed."
            })

        # 9. Session Lock / Unlock
        if path == "/api/session/lock":
            is_session_locked = True
            return self._send_json(200, {
                "success": True,
                "locked": True,
                "message": "Session locked."
            })

        if path == "/api/session/unlock":
            is_session_locked = False
            return self._send_json(200, {
                "success": True,
                "locked": False,
                "message": "Session unlocked."
            })

        # 10. Policy Mutations (Create / Update / Bulk Update)
        if path == "/api/policies":
            if "policies" in payload and isinstance(payload["policies"], list):
                valid_list = []
                for p in payload["policies"]:
                    app_name = str(p.get("application", "")).strip()
                    if not app_name:
                        continue
                    mode = str(p.get("mode", "BLOCK")).upper()
                    if mode not in ("BLOCK", "CONTENT_AWARE", "ALLOW"):
                        mode = "BLOCK"
                    max_dur = int(p.get("maxDurationSeconds", 60))
                    cooldown = int(p.get("cooldownSeconds", 3600))
                    desc = str(p.get("description", f"Policy for {app_name}"))
                    icon = str(p.get("icon", "shield"))
                    valid_list.append({
                        "application": app_name,
                        "mode": mode,
                        "maxDurationSeconds": max_dur,
                        "cooldownSeconds": cooldown,
                        "icon": icon,
                        "description": desc
                    })
                if save_policies(valid_list):
                    return self._send_json(200, {"success": True, "policies": valid_list})
                else:
                    return self._send_json(500, {"success": False, "error": "Failed to persist policies"})

            app_name = payload.get("application", "").strip()
            mode = payload.get("mode", "BLOCK").upper()
            if mode not in ("BLOCK", "CONTENT_AWARE", "ALLOW"):
                mode = "BLOCK"
            max_dur = int(payload.get("maxDurationSeconds", 60))
            cooldown = int(payload.get("cooldownSeconds", 3600))
            description = payload.get("description", f"Policy for {app_name}")
            icon = payload.get("icon", "shield")

            if not app_name:
                return self._send_json(400, {"success": False, "error": "Application name required"})

            policies_list = load_policies()
            existing_idx = next((i for i, p in enumerate(policies_list) if p.get("application", "").lower() == app_name.lower()), -1)
            
            new_record = {
                "application": app_name,
                "mode": mode,
                "maxDurationSeconds": max_dur,
                "cooldownSeconds": cooldown,
                "icon": icon,
                "description": description
            }

            if existing_idx >= 0:
                policies_list[existing_idx] = new_record
            else:
                policies_list.append(new_record)

            if save_policies(policies_list):
                return self._send_json(200, {"success": True, "policies": policies_list})
            else:
                return self._send_json(500, {"success": False, "error": "Failed to persist policy"})

        # 11. Policy Presets
        if path == "/api/policies/preset":
            preset = payload.get("preset", "balanced").lower()
            if preset == "strict":
                active_policy_name = "Strict Exam"
                new_policies = [
                    { "application": "Instagram", "mode": "BLOCK", "maxDurationSeconds": 15, "cooldownSeconds": 7200, "icon": "camera", "description": "Strict 15s limit with 2h lockout." },
                    { "application": "YouTube", "mode": "BLOCK", "maxDurationSeconds": 30, "cooldownSeconds": 7200, "icon": "play", "description": "Complete video ban during focus sessions." },
                    { "application": "Snapchat", "mode": "BLOCK", "maxDurationSeconds": 15, "cooldownSeconds": 7200, "icon": "message-circle", "description": "Strict social media ban." },
                    { "application": "Reddit", "mode": "BLOCK", "maxDurationSeconds": 15, "cooldownSeconds": 7200, "icon": "globe", "description": "Social media forum feed banned." },
                    { "application": "VS Code", "mode": "ALLOW", "maxDurationSeconds": 0, "cooldownSeconds": 0, "icon": "code-2", "description": "Whitelisted coding environment." }
                ]
            elif preset == "relaxed":
                active_policy_name = "Relaxed Study"
                new_policies = [
                    { "application": "Instagram", "mode": "BLOCK", "maxDurationSeconds": 120, "cooldownSeconds": 1800, "icon": "camera", "description": "Relaxed 2m limit." },
                    { "application": "YouTube", "mode": "CONTENT_AWARE", "maxDurationSeconds": 180, "cooldownSeconds": 1800, "icon": "play", "description": "Educational content allowed." },
                    { "application": "Snapchat", "mode": "BLOCK", "maxDurationSeconds": 120, "cooldownSeconds": 1800, "icon": "message-circle", "description": "Relaxed 2m limit." },
                    { "application": "VS Code", "mode": "ALLOW", "maxDurationSeconds": 0, "cooldownSeconds": 0, "icon": "code-2", "description": "Coding environment." }
                ]
            else:
                active_policy_name = "Balanced"
                new_policies = list(DEFAULT_POLICIES)

            if save_policies(new_policies):
                return self._send_json(200, {"success": True, "preset": preset, "policies": new_policies})
            else:
                return self._send_json(500, {"success": False, "error": "Failed to apply preset"})

        # 12. Acknowledge Intervention
        if path == "/api/intervention/acknowledge":
            return self._send_json(200, {
                "success": True,
                "message": "Intervention acknowledged. Focus restored."
            })

        self.send_error(404, "Endpoint not found")

    def do_DELETE(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/policies":
            params = urllib.parse.parse_qs(parsed_url.query)
            app_target = params.get("application", [""])[0].strip().lower()

            if not app_target:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    try:
                        body = self.rfile.read(content_length).decode('utf-8')
                        body_json = json.loads(body)
                        app_target = body_json.get("application", "").strip().lower()
                    except Exception:
                        pass

            if not app_target:
                return self._send_json(400, {"success": False, "error": "Application name required for deletion"})

            policies_list = load_policies()
            filtered = [p for p in policies_list if p.get("application", "").lower() != app_target]
            if save_policies(filtered):
                return self._send_json(200, {"success": True, "policies": filtered})
            else:
                return self._send_json(500, {"success": False, "error": "Failed to save updated policies"})

        self.send_error(404, "Endpoint not found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def find_available_port(start_port):
    port = start_port
    while port < start_port + 100:
        if not is_port_in_use(port):
            return port
        port += 1
    return start_port


def start_presence_monitor():
    """Continuously verifies if the enrolled user is watching the screen in the background."""
    def _worker():
        global last_presence_state, last_presence_timestamp
        while True:
            try:
                time.sleep(3.5)
                # If UI dashboard has sent live camera frame recently (< 5.0s ago), skip backend capture
                if (time.time() - last_presence_timestamp) < 5.0:
                    continue

                if HAS_FACE_AUTH:
                    engine = get_face_auth_engine()
                    enrolled = engine.list_enrolled_users()
                    if enrolled:
                        curr = get_current_user()
                        res = engine.check_presence(user_id=curr)
                        last_presence_state = res
            except Exception as e:
                time.sleep(4.0)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def run_server(requested_port=DEFAULT_PORT):
    os.chdir(UI_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    
    port = requested_port
    if is_port_in_use(port):
        print(f"[!] Port {port} is currently in use.")
        port = find_available_port(port + 1)
        print(f"[*] Automatically switched to available port: {port}\n")

    start_presence_monitor()

    try:
        with http.server.ThreadingHTTPServer(("0.0.0.0", port), FocusGuardRequestHandler) as httpd:
            print("=" * 65)
            print("     FOCUS GUARD UI & BIOMETRIC AUTH DASHBOARD")
            print("=" * 65)
            print(f"\n  🚀 Serving at: http://localhost:{port}")
            print(f"  🔐 Face Auth: {'Enabled (OpenCV YuNet + SFace)' if HAS_FACE_AUTH else 'Active (Fallback Simulator)'}")
            print(f"  📁 Directory : {UI_DIR}")
            print(f"\n  👉 Open http://localhost:{port} in your browser.")
            print("  Press Ctrl+C to stop the server.\n")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down FocusGuard UI Server...")
    except Exception as e:
        print(f"[Error] Failed to start server: {e}")


if __name__ == "__main__":
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_server(port)
