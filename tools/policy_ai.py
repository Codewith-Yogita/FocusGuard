"""
FocusGuard AI Policy Assistance
Provides non-binding policy suggestions and natural-language policy parsing.
Enforcement remains strictly deterministic—user must confirm all suggestions.
"""

import json
import re
from typing import Dict, Any, List
try:
    from tools.llm_provider import ProviderManager
except ImportError:
    from llm_provider import ProviderManager


class PolicyAIAssistant:
    def __init__(self, provider_manager: ProviderManager):
        self.provider = provider_manager

    def suggest_policies(self, observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Suggests potential FocusGuard policies based on distraction observations."""
        system_prompt = (
            "You are FocusGuard's policy advisor. Based on usage observations, suggest 1 to 3 "
            "helpful focus policies. Remember: users must review and approve all suggestions. "
            "Respond ONLY with a JSON array of suggestions:\n"
            "[\n"
            "  {\n"
            '    "application": "...",\n'
            '    "mode": "BLOCK|CONTENT_AWARE|ALLOW",\n'
            '    "max_duration_seconds": 60,\n'
            '    "cooldown_seconds": 1800,\n'
            '    "reason": "..."\n'
            "  }\n"
            "]"
        )

        user_prompt = f"Observations: {json.dumps(observations)}"

        llm_response = self.provider.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=250,
            temperature=0.5,
            timeout=2.5
        )

        if llm_response:
            try:
                match = re.search(r"\[[\s\S]*\]", llm_response)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list):
                        return parsed
            except Exception:
                pass

        # Fallback heuristic suggestions
        return [
            {
                "application": "YouTube",
                "mode": "CONTENT_AWARE",
                "max_duration_seconds": 60,
                "cooldown_seconds": 1800,
                "reason": "Allows learning and tutorial videos while preventing rabbit holes."
            }
        ]

    def parse_natural_policy(self, text: str) -> Dict[str, Any]:
        """Parses natural language policy commands (e.g. 'block instagram after 20 minutes')."""
        system_prompt = (
            "Convert this natural language focus rule into a structured FocusGuard policy. "
            "Respond ONLY with valid JSON in this exact structure:\n"
            "{\n"
            '  "application": "...",\n'
            '  "mode": "BLOCK|CONTENT_AWARE|ALLOW",\n'
            '  "max_duration_seconds": 60,\n'
            '  "cooldown_seconds": 3600,\n'
            '  "explanation": "..."\n'
            "}"
        )

        llm_response = self.provider.generate(
            prompt=f"Rule: {text}",
            system_prompt=system_prompt,
            max_tokens=200,
            temperature=0.0,
            timeout=2.0
        )

        if llm_response:
            try:
                match = re.search(r"\{[\s\S]*\}", llm_response)
                if match:
                    res = json.loads(match.group(0))
                    if "application" in res and "mode" in res:
                        return res
            except Exception:
                pass

        # Regex fallback for common phrases
        lower = text.lower()
        app = "Unknown"
        mode = "BLOCK"
        max_dur = 60
        cooldown = 1800

        for candidate in ["instagram", "youtube", "snapchat", "tiktok", "twitter", "reddit", "facebook"]:
            if candidate in lower:
                app = candidate.capitalize()
                break

        if "content aware" in lower or "shorts" in lower:
            mode = "CONTENT_AWARE"
        elif "allow" in lower:
            mode = "ALLOW"

        # Look for duration
        dur_match = re.search(r"(\d+)\s*(?:min|minute|seconds|sec)", lower)
        if dur_match:
            num = int(dur_match.group(1))
            if "sec" in lower:
                max_dur = num
            else:
                max_dur = num * 60

        return {
            "application": app,
            "mode": mode,
            "max_duration_seconds": max_dur,
            "cooldown_seconds": cooldown,
            "explanation": f"Parsed rule for {app} in {mode} mode with {max_dur}s limit."
        }

    def parse_goal_session(self, text: str) -> Dict[str, Any]:
        """Parses a user focus session goal (e.g. 'I want to study DSA for 2 hours').
        Extracts topic, duration in minutes, and relevant positive keywords.
        """
        system_prompt = (
            "You are FocusGuard's session goal analyzer. Given a user goal, extract the core topic, "
            "the duration in minutes, and 5-10 positive topic keywords that are directly relevant. "
            "Respond ONLY with a JSON object in this exact schema:\n"
            "{\n"
            '  "topic": "...",\n'
            '  "duration_minutes": 120,\n'
            '  "positive_keywords": ["..."],\n'
            '  "summary": "..."\n'
            "}"
        )

        llm_response = self.provider.generate(
            prompt=f"Goal: {text}",
            system_prompt=system_prompt,
            max_tokens=220,
            temperature=0.0,
            timeout=2.0
        )

        if llm_response:
            try:
                match = re.search(r"\{[\s\S]*\}", llm_response)
                if match:
                    res = json.loads(match.group(0))
                    if "topic" in res and "duration_minutes" in res:
                        return res
            except Exception:
                pass

        # Robust regex fallback
        lower = text.lower()
        duration = 60
        dur_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr|hours)", lower)
        if dur_match:
            duration = int(float(dur_match.group(1)) * 60)
        else:
            min_match = re.search(r"(\d+)\s*(?:min|minute|minutes)", lower)
            if min_match:
                duration = int(min_match.group(1))

        topic = text
        for prefix in ["i want to study", "i want to learn", "i want to work on", "i want to code", "study", "work on", "focus on"]:
            if lower.startswith(prefix):
                topic = text[len(prefix):].strip()
                break
        topic = re.sub(r"(?:for\s+\d+.*)$", "", topic, flags=re.IGNORECASE).strip(" ,.-")
        if not topic:
            topic = "Focused Study"

        keywords = [w for w in re.split(r"[\s,]+", topic.lower()) if len(w) > 2]
        if "dsa" in lower:
            keywords.extend(["data structure", "algorithm", "leetcode", "tree", "graph", "binary", "sorting", "striver", "array", "recursion"])

        return {
            "topic": topic,
            "duration_minutes": duration,
            "positive_keywords": list(set(keywords)),
            "summary": f"Focus session on {topic} for {duration} minutes."
        }

    def evaluate_goal_relevance(self, app: str, title: str, url: str, goal: str) -> Dict[str, Any]:
        """Evaluates whether the active window/video/tab is relevant to the active goal.
        Returns {"relevant": bool, "classification": "PRODUCTIVE"|"DISTRACTION", "reason": "..."}.
        """
        if not goal:
            return {"relevant": True, "classification": "PRODUCTIVE", "reason": "No active goal restriction"}

        lower_title = title.lower()
        lower_goal = goal.lower()

        # Obvious developer tools & IDEs always allowed
        dev_tools = [
            "antigravity", "cursor", "visual studio code", "vs code", "pycharm",
            "clion", "terminal", "powershell", "cmd.exe", "github", "sublime",
            "windsurf", "intellij", "devenv", "notepad++", "git"
        ]
        for dev in dev_tools:
            if dev in app.lower() or dev in lower_title:
                return {
                    "relevant": True,
                    "classification": "PRODUCTIVE",
                    "reason": f"Core development tool ({app}) allowed for focus session"
                }

        # Any coding files
        code_exts = [".cpp", ".h", ".py", ".java", ".c", ".js", ".ts", ".rs", ".go", ".html", ".css", ".json"]
        if any(ext in lower_title for ext in code_exts):
            return {
                "relevant": True,
                "classification": "PRODUCTIVE",
                "reason": f"Active coding file in {app} allowed for focus session"
            }

        # Instant Shorts check (YouTube Shorts are strictly distracting regardless of study topic)
        if "/shorts" in url or "#shorts" in lower_title or (app in ["chrome.exe", "msedge.exe", "brave.exe"] and "shorts" in lower_title):
            return {
                "relevant": False,
                "classification": "DISTRACTION",
                "reason": "YouTube Shorts and vertical feeds are strictly classified as distraction."
            }

        # Instant DSA fastpath if goal is DSA-focused
        dsa_terms = [
            "dsa", "data structure", "data structures", "algorithm", "algorithms",
            "leetcode", "codeforces", "codechef", "tree", "graph", "sorting",
            "binary search", "recursion", "dynamic programming", " dp ", "array",
            "linked list", "stack", "queue", "heap", "trie", "backtracking",
            "greedy", "striver", "neetcode", "babbar", "kunal kushwaha", "geeksforgeeks"
        ]
        if "dsa" in lower_goal or "algorithm" in lower_goal:
            if any(t in lower_title for t in dsa_terms):
                return {
                    "relevant": True,
                    "classification": "PRODUCTIVE",
                    "reason": "Directly matches active DSA study topics (Data Structures & Algorithms)"
                }

        system_prompt = (
            f"You are FocusGuard. The user's active goal is: '{goal}'.\n"
            "Determine if the current activity/video is RELEVANT and productive for this goal, "
            "or an UNRELATED DISTRACTION (e.g. gaming, entertainment, comedy, tech drama, news, vlogs, music, social media, random shorts).\n"
            "Respond ONLY with a JSON object in this schema:\n"
            "{\n"
            '  "relevant": true,\n'
            '  "classification": "PRODUCTIVE",\n'
            '  "reason": "..."\n'
            "}\n"
            "Set relevant=false and classification='DISTRACTION' if it is unrelated to the goal."
        )

        user_prompt = f"App: {app}\nTitle: {title}\nURL: {url}"

        llm_response = self.provider.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=100,
            temperature=0.0,
            timeout=3.0
        )

        if llm_response:
            try:
                match = re.search(r"\{[\s\S]*\}", llm_response)
                if match:
                    res = json.loads(match.group(0))
                    if "classification" in res and "relevant" in res:
                        # Ensure fields are properly formatted
                        res["classification"] = str(res["classification"]).upper()
                        if res["classification"] not in ("PRODUCTIVE", "DISTRACTION", "NEUTRAL"):
                            res["classification"] = "PRODUCTIVE" if res["relevant"] else "DISTRACTION"
                        return res
            except Exception:
                pass

        # Heuristic fallback if LLM is unreachable or times out
        if "dsa" in lower_goal or "algorithm" in lower_goal:
            if any(t in lower_title for t in dsa_terms):
                return {"relevant": True, "classification": "PRODUCTIVE", "reason": "DSA study content matched"}
            else:
                return {"relevant": False, "classification": "DISTRACTION", "reason": f"Content does not relate to your goal: {goal}"}

        # For any general goal, if on YouTube and not matching, treat as distraction
        if "youtube" in lower_title or "youtube.com" in url.lower():
            return {"relevant": False, "classification": "DISTRACTION", "reason": f"YouTube video not verified for active goal: {goal}"}

        return {"relevant": True, "classification": "PRODUCTIVE", "reason": "Allowed under active session"}

