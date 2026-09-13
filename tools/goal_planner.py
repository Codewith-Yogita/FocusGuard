"""
FocusGuard AI Goal Planner
Integrates Groq LLM inference with deterministic schedule math and policy validation.
Converts natural language goals into structured, customizable focus sessions.
"""

import os
import sys
import re
import json
import uuid
import time
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_provider import GroqProvider, load_env_file

load_env_file()


# ============================================================================
# 1. DURATION PARSER & AMBIGUITY DETECTOR
# ============================================================================

def parse_duration(text: str) -> Dict[str, Any]:
    """
    Parses duration from natural language goal text.
    Handles hours, minutes, composite expressions ('1h 30m'), and detects ambiguous inputs ('for 12').
    """
    t = text.lower().strip()

    # Check for ambiguous standalone numbers like "for 12" without units
    ambiguous_match = re.search(r'\b(?:for|in)\s+(\d{1,2})\b(?!\s*(?:hours?|hrs?|h|minutes?|mins?|m|am|pm|o\'clock|days?))', t)
    if ambiguous_match:
        num = ambiguous_match.group(1)
        return {
            "status": "needs_clarification",
            "question": f"Does ‘{num}’ mean {num} minutes, {num} hours, or until {num}:00?",
            "options": [f"{num} minutes", f"{num} hours", f"Until {num}:00"]
        }

    total_minutes = 0
    found_any = False

    # Composite or single hours: e.g. "2 hours", "1.5 hrs", "2h", "1 hr"
    hr_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b', t)
    if hr_match:
        total_minutes += int(float(hr_match.group(1)) * 60)
        found_any = True

    # Minutes: e.g. "45 minutes", "90 mins", "30m"
    min_match = re.search(r'(\d+)\s*(?:minutes?|mins?|m)\b', t)
    if min_match:
        total_minutes += int(min_match.group(1))
        found_any = True

    # Check for "until X" (e.g. "until 5pm", "until 17:00")
    until_match = re.search(r'until\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', t)
    if until_match and not found_any:
        hr = int(until_match.group(1))
        mn = int(until_match.group(2) or 0)
        ampm = until_match.group(3)
        if ampm == "pm" and hr < 12:
            hr += 12
        elif ampm == "am" and hr == 12:
            hr = 0
        now = time.localtime()
        target_mins = hr * 60 + mn
        current_mins = now.tm_hour * 60 + now.tm_min
        diff = target_mins - current_mins
        if diff <= 0:
            diff += 24 * 60  # next day
        total_minutes = max(15, min(720, diff))
        found_any = True

    if not found_any or total_minutes <= 0:
        # Default suggested duration
        return {
            "status": "inferred",
            "totalMinutes": 60,
            "wasDefault": True,
            "note": "No explicit duration specified. Suggested duration: 60 minutes."
        }

    # Clamp to practical bounds: 10 minutes to 12 hours
    clamped_minutes = max(10, min(720, total_minutes))
    return {
        "status": "ok",
        "totalMinutes": clamped_minutes,
        "wasDefault": False
    }


# ============================================================================
# 2. DETERMINISTIC SCHEDULE BUILDER
# ============================================================================

def build_deterministic_schedule(
    total_minutes: int,
    strategy: str = "custom_pomodoro",
    custom_focus: Optional[int] = None,
    custom_break: Optional[int] = None
) -> Tuple[str, List[Dict[str, Any]], Dict[str, int]]:
    """
    Computes exact focus, break, and review intervals matching total_minutes.
    Breaks are strictly included inside total_minutes so elapsed time equals requested session time.
    """
    total_minutes = int(total_minutes)
    
    # Strategy configurations
    if strategy == "deep_work":
        f_min = custom_focus or 50
        b_min = custom_break or 10
        long_b_min = 15
        rev_min = 5
    elif strategy == "sprint":
        f_min = custom_focus or 15
        b_min = custom_break or 3
        long_b_min = 5
        rev_min = 3
    elif strategy == "continuous":
        f_min = max(10, total_minutes - (5 if total_minutes > 25 else 0))
        b_min = 0
        long_b_min = 0
        rev_min = 5 if total_minutes > 25 else 0
    else:  # custom_pomodoro
        f_min = custom_focus or 25
        b_min = custom_break or 5
        long_b_min = 10
        rev_min = 5

    intervals = []

    # Very short session (< 35 minutes)
    if total_minutes <= 35:
        rev = 5 if total_minutes >= 25 else 0
        focus_time = total_minutes - rev
        intervals.append({
            "index": 1,
            "type": "focus",
            "title": "Focus Session",
            "durationMinutes": focus_time
        })
        if rev > 0:
            intervals.append({
                "index": 2,
                "type": "review",
                "title": "Wrap-up & Review",
                "durationMinutes": rev
            })
        cum_min = 0
        for it in intervals:
            dur = it.get("durationMinutes", 0)
            it["duration_minutes"] = dur
            it["start_minute"] = cum_min
            it["startMinute"] = cum_min
            cum_min += dur
            it["end_minute"] = cum_min
            it["endMinute"] = cum_min
            it["label"] = it.get("title", f"Interval {it.get('index', 1)}")
            it["interval_index"] = it.get("index", 1)

        return strategy, intervals, {
            "focusMinutes": focus_time,
            "shortBreakMinutes": 0,
            "longBreakMinutes": 0,
            "reviewMinutes": rev
        }

    # Multiple intervals: calculate how many blocks fit in (total_minutes - rev_min)
    available_time = total_minutes - rev_min
    cycle_time = f_min + b_min
    
    num_cycles = max(1, round(available_time / cycle_time))
    
    # Adjust focus length to exactly match total_minutes
    actual_breaks_count = num_cycles - 1
    total_break_time = actual_breaks_count * b_min
    total_focus_time = total_minutes - total_break_time - rev_min
    
    if total_focus_time < (num_cycles * 10):
        # Scale back number of cycles if focus blocks become too short
        num_cycles = max(1, num_cycles - 1)
        actual_breaks_count = num_cycles - 1
        total_break_time = actual_breaks_count * b_min
        total_focus_time = total_minutes - total_break_time - rev_min

    # Distribute focus time among blocks
    base_focus = total_focus_time // num_cycles
    remainder = total_focus_time % num_cycles

    idx = 1
    for i in range(num_cycles):
        block_dur = base_focus + (1 if i < remainder else 0)
        intervals.append({
            "index": idx,
            "type": "focus",
            "title": f"Focus Block {i + 1}",
            "durationMinutes": block_dur
        })
        idx += 1

        # Add break between focus blocks (not after the final block)
        if i < num_cycles - 1:
            is_long = (i > 0 and (i + 1) % 3 == 0)
            break_dur = long_b_min if is_long else b_min
            intervals.append({
                "index": idx,
                "type": "long_break" if is_long else "short_break",
                "title": "Long Recovery Break" if is_long else "Short Break",
                "durationMinutes": break_dur
            })
            idx += 1

    # Final review block
    if rev_min > 0:
        intervals.append({
            "index": idx,
            "type": "review",
            "title": "Wrap-up & Session Review",
            "durationMinutes": rev_min
        })

    # Assert exact sum
    computed_sum = sum(item["durationMinutes"] for item in intervals)
    diff = total_minutes - computed_sum
    if diff != 0 and len(intervals) > 0:
        intervals[0]["durationMinutes"] += diff

    # Populate timing offsets and cross-compatibility keys (snake_case + camelCase)
    cum_min = 0
    for it in intervals:
        dur = it.get("durationMinutes", 0)
        it["duration_minutes"] = dur
        it["start_minute"] = cum_min
        it["startMinute"] = cum_min
        cum_min += dur
        it["end_minute"] = cum_min
        it["endMinute"] = cum_min
        it["label"] = it.get("title", f"Interval {it.get('index', 1)}")
        it["interval_index"] = it.get("index", 1)

    return strategy, intervals, {
        "focusMinutes": f_min,
        "shortBreakMinutes": b_min,
        "longBreakMinutes": long_b_min,
        "reviewMinutes": rev_min
    }


# ============================================================================
# 3. GROQ LLM PLANNER INFERENCE
# ============================================================================

SYSTEM_PLANNER_PROMPT = """You are FocusGuard's intelligent Goal Planning Engine.
Your role is to understand user focus goals and generate a structured JSON profile for deterministic focus enforcement.
Rules:
1. Output MUST be valid JSON only. Do not include markdown code blocks, backticks, or any additional text.
2. Infer the subject, title, allowed applications, allowed website domains, allowed URL patterns, allowed keywords, and blocked distractions based on the goal.
3. Keep default blocked applications focused on common high-distraction sites: Instagram, Snapchat, Reddit, TikTok.
4. Allow specific educational resources (e.g. LeetCode, GitHub, documentation, VS Code) if relevant to the subject.
5. If YouTube is relevant (e.g. tutorials, DSA lectures), allow youtube.com/watch* under Content-Aware mode and block youtube.com/shorts/*.

Response JSON Schema:
{
  "goalTitle": "Brief 2-4 word goal title",
  "subject": "Topic or activity (e.g. DSA, C++, Machine Learning, Writing)",
  "description": "Short 1-sentence summary of the focus objective",
  "strategy": "custom_pomodoro | deep_work | sprint | continuous",
  "allowedApplications": ["Visual Studio Code", "Terminal"],
  "allowedDomains": ["leetcode.com", "geeksforgeeks.org"],
  "allowedUrlPatterns": ["youtube.com/watch*"],
  "allowedKeywords": ["keyword1", "keyword2"],
  "blockedApplications": ["Instagram", "Snapchat"],
  "blockedDomains": ["instagram.com", "tiktok.com", "reddit.com"],
  "blockedUrlPatterns": ["youtube.com/shorts/*"],
  "allowBackgroundMusic": true,
  "requireContentAwareness": true,
  "warningAfterSeconds": 5,
  "interveneAfterSeconds": 10,
  "blockAfterSeconds": 15,
  "cooldownSeconds": 300,
  "explanation": "Brief explanation of how the plan enforces focus while allowing necessary tools."
}
"""

def call_groq_planner(goal_text: str, preferences: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Calls Groq API to extract semantic context rules and explanations.
    Falls back gracefully to deterministic rule generation if Groq is unavailable.
    """
    prefs = preferences or {}
    provider = GroqProvider()

    user_payload = {
        "user_goal": goal_text,
        "preferences": {
            "strictness": prefs.get("strictness", "balanced"),
            "allowBackgroundMusic": prefs.get("allowBackgroundMusic", True),
            "allowEducationalYouTube": prefs.get("allowEducationalYouTube", True),
            "defaultWarningSeconds": prefs.get("defaultWarningSeconds", 5)
        }
    }

    if provider.is_configured() and provider.circuit.is_available():
        try:
            resp_text = provider.generate(
                prompt=json.dumps(user_payload),
                system_prompt=SYSTEM_PLANNER_PROMPT,
                max_tokens=650,
                temperature=0.2,
                timeout=5.0
            )

            if resp_text:
                cleaned = resp_text.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                    cleaned = re.sub(r"\s*```$", "", cleaned)
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict) and "goalTitle" in parsed:
                    parsed["plannerSource"] = "groq_api"
                    return parsed
        except Exception as ex:
            print(f"[GoalPlanner Groq Error] {ex}. Falling back to deterministic planner.")

    # Deterministic Rule Extraction Fallback
    return generate_deterministic_fallback_rules(goal_text, prefs)


def generate_deterministic_fallback_rules(goal_text: str, prefs: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic rule extractor when LLM is unavailable."""
    gt = goal_text.lower()

    title = "Focus Session"
    subject = "Deep Work"
    allowed_apps = ["Visual Studio Code", "Terminal", "Notion", "Obsidian"]
    allowed_domains = ["github.com", "stackoverflow.com", "google.com"]
    keywords = ["study", "work", "focus", "research"]

    if any(w in gt for w in ["dsa", "leetcode", "algorithm", "data structure"]):
        title = "Study DSA"
        subject = "DSA"
        allowed_apps = ["Visual Studio Code", "CLion", "Terminal", "Notion", "Obsidian", "PDF Reader"]
        allowed_domains = ["leetcode.com", "geeksforgeeks.org", "cp-algorithms.com", "github.com", "hackerrank.com"]
        keywords = ["DSA", "data structures", "algorithms", "graph", "tree", "dynamic programming", "C++", "complexity", "LeetCode"]
    elif any(w in gt for w in ["c++", "cpp", "coding", "program"]):
        title = "C++ Development"
        subject = "C++"
        allowed_apps = ["Visual Studio Code", "CLion", "Visual Studio", "Terminal", "GitKraken"]
        allowed_domains = ["cppreference.com", "github.com", "stackoverflow.com", "learncpp.com"]
        keywords = ["C++", "compiler", "header", "std::", "cmake", "debug", "function"]
    elif any(w in gt for w in ["os", "operating system", "linux", "kernel"]):
        title = "Operating Systems Study"
        subject = "Operating Systems"
        allowed_apps = ["Visual Studio Code", "Terminal", "PDF Reader", "Notion"]
        allowed_domains = ["kernel.org", "geeksforgeeks.org", "github.com"]
        keywords = ["process", "thread", "memory", "virtual memory", "paging", "scheduling", "deadlock"]

    return {
        "goalTitle": title,
        "subject": subject,
        "description": f"Dedicated focus on {subject} with deterministic distraction filtering.",
        "strategy": "custom_pomodoro",
        "allowedApplications": allowed_apps,
        "allowedDomains": allowed_domains,
        "allowedUrlPatterns": ["youtube.com/watch*"],
        "allowedKeywords": keywords,
        "blockedApplications": ["Instagram", "Snapchat", "TikTok"],
        "blockedDomains": ["instagram.com", "web.snapchat.com", "reddit.com", "tiktok.com"],
        "blockedUrlPatterns": ["youtube.com/shorts/*"],
        "allowBackgroundMusic": prefs.get("allowBackgroundMusic", True),
        "requireContentAwareness": True,
        "warningAfterSeconds": int(prefs.get("defaultWarningSeconds", 5)),
        "interveneAfterSeconds": 10,
        "blockAfterSeconds": 15,
        "cooldownSeconds": 300,
        "explanation": f"The plan organizes focus on {subject}. Productive tools and reference documentation are allowed, while social media and vertical short videos are blocked.",
        "plannerSource": "deterministic_fallback"
    }


# ============================================================================
# 4. FULL PLAN GENERATION & VALIDATION PIPELINE
# ============================================================================

def generate_focus_plan(goal_text: str, preferences: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Master pipeline:
    1. Parses duration & checks ambiguity.
    2. Calls Groq LLM (or deterministic fallback) for semantic rules.
    3. Builds exact deterministic timeline.
    4. Normalizes and validates policy and escalation constraints.
    """
    if not goal_text or not goal_text.strip():
        return {
            "status": "error",
            "message": "Goal text cannot be empty. Please enter a focus goal."
        }

    dur_info = parse_duration(goal_text)
    if dur_info.get("status") == "needs_clarification":
        return dur_info

    total_mins = dur_info.get("totalMinutes", 60)
    ai_rules = call_groq_planner(goal_text, preferences)

    # Strategy & Timeline
    strategy = ai_rules.get("strategy", "custom_pomodoro")
    strategy_used, intervals, strat_details = build_deterministic_schedule(
        total_minutes=total_mins,
        strategy=strategy
    )

    plan_id = f"plan-{uuid.uuid4().hex[:10]}"

    # Policy Deduplication & Validation
    allowed_apps = list(dict.fromkeys(ai_rules.get("allowedApplications", [])))
    blocked_apps = list(dict.fromkeys(ai_rules.get("blockedApplications", [])))
    # Resolve allow/block conflict in apps: blocked overrides allowed if both exist
    allowed_apps = [a for a in allowed_apps if a.lower() not in [b.lower() for b in blocked_apps]]

    allowed_doms = list(dict.fromkeys(ai_rules.get("allowedDomains", [])))
    blocked_doms = list(dict.fromkeys(ai_rules.get("blockedDomains", [])))
    allowed_doms = [d for d in allowed_doms if d.lower() not in [b.lower() for b in blocked_doms]]

    # Delays validation: warning <= intervene <= block
    warn_sec = max(0, int(ai_rules.get("warningAfterSeconds", 5)))
    interv_sec = max(warn_sec, int(ai_rules.get("interveneAfterSeconds", 10)))
    block_sec = max(interv_sec, int(ai_rules.get("blockAfterSeconds", 15)))

    plan = {
        "planId": plan_id,
        "plan_id": plan_id,
        "status": "draft",
        "plannerSource": ai_rules.get("plannerSource", "groq_api"),
        "goal_title": ai_rules.get("goalTitle", "Focus Session"),
        "goal": {
            "title": ai_rules.get("goalTitle", "Focus Session"),
            "description": ai_rules.get("description", goal_text),
            "subject": ai_rules.get("subject", "General Focus"),
            "rawText": goal_text,
            "totalDurationMinutes": total_mins,
            "total_duration_minutes": total_mins,
            "wasDurationInferred": dur_info.get("wasDefault", False)
        },
        "schedule": {
            "strategy": strategy_used,
            "totalDurationMinutes": total_mins,
            "total_duration_minutes": total_mins,
            "focusMinutes": strat_details.get("focusMinutes", 25),
            "focus_block_minutes": strat_details.get("focusMinutes", 25),
            "shortBreakMinutes": strat_details.get("shortBreakMinutes", 5),
            "short_break_minutes": strat_details.get("shortBreakMinutes", 5),
            "longBreakMinutes": strat_details.get("longBreakMinutes", 10),
            "reviewMinutes": strat_details.get("reviewMinutes", 5),
            "intervals": intervals
        },
        "policy": {
            "mode": "GOAL_SCOPED",
            "strictness": (preferences or {}).get("strictness", "balanced"),
            "allowedApplications": allowed_apps,
            "allowed_applications": allowed_apps,
            "allowedDomains": allowed_doms,
            "allowed_domains": allowed_doms,
            "allowedUrlPatterns": ai_rules.get("allowedUrlPatterns", ["youtube.com/watch*"]),
            "allowedKeywords": ai_rules.get("allowedKeywords", []),
            "allowed_keywords": ai_rules.get("allowedKeywords", []),
            "blockedApplications": blocked_apps,
            "blocked_applications": blocked_apps,
            "blockedDomains": blocked_doms,
            "blocked_domains": blocked_doms,
            "blockedUrlPatterns": ai_rules.get("blockedUrlPatterns", ["youtube.com/shorts/*"]),
            "allowBackgroundMusic": bool(ai_rules.get("allowBackgroundMusic", True)),
            "requireContentAwareness": bool(ai_rules.get("requireContentAwareness", True)),
            "warningAfterSeconds": warn_sec,
            "warning_after_seconds": warn_sec,
            "interveneAfterSeconds": interv_sec,
            "intervene_after_seconds": interv_sec,
            "blockAfterSeconds": block_sec,
            "block_after_seconds": block_sec,
            "cooldownSeconds": int(ai_rules.get("cooldownSeconds", 300)),
            "escalation": {
                "warning_delay_seconds": warn_sec,
                "block_delay_seconds": block_sec
            }
        },
        "explanation": ai_rules.get("explanation", "Deterministic FocusGuard enforcement plan generated.")
    }

    return plan
