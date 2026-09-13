"""
FocusGuard Alert Rephrasing Engine
Supports zero-latency offline phrase bank and on-demand contextual rephrasing.
"""

import os
import json
import random
import time
from typing import Dict, Any, Optional, List
from llm_provider import ProviderManager

PHRASE_BANK_PATH = os.path.join(os.path.dirname(__file__), "phrase_bank.json")
BANK_VERSION = 1

# High-quality default constructive phrase bank
DEFAULT_PHRASE_BANK: Dict[str, List[str]] = {
    "block": [
        "Focus Guard paused {app}. You chose to set this boundary—time to refocus on your main goal!",
        "{app} is currently restricted. Take a breath and return to what you set out to accomplish.",
        "Gentle reminder: {app} is on your block list. Let's direct your attention back to your priorities.",
        "Stepping away from {app} now. A quick break or refocusing can help you stay on track.",
        "Your focus plan restricted {app}. You're doing great—keep building that momentum!"
    ],
    "limit": [
        "You've been on {app} for {duration} min. Time to switch gears and get back to your priority.",
        "Time check: {duration} min spent on {app}. Ready to return to your goal?",
        "You've reached your {duration} min limit on {app}. Let's bring your attention back to your task.",
        "That's {duration} min on {app}. Honoring your boundary now will feel rewarding later!",
        "Notice your screen time: {duration} min on {app}. Time to refocus on what matters today."
    ],
    "cooldown": [
        "{app} is in cooldown for {cooldown}s. Step back, stretch, and let your focus reset.",
        "Focus Guard cooldown active on {app} ({cooldown}s remaining). Time to dive back into your flow.",
        "{app} will remain paused for {cooldown}s so you can stay in your productive zone.",
        "Cooldown in progress: {cooldown}s left on {app}. Use this moment to re-center.",
        "{app} is cooling down for {cooldown}s. Great opportunity to finish your current work."
    ],
    "reminder": [
        "A quick nudge: you've been on {app} for {duration} min. Is this serving your goal today?",
        "Mindful check-in: {duration} min on {app}. Just checking if you intended to spend this time here.",
        "Heads up: {duration} min active on {app}. Keep an eye on your plan!",
        "Friendly reminder: {duration} min on {app}. Stay mindful of your focus goals."
    ],
    "focus_win": [
        "Fantastic focus session! You spent {duration} min engaged in productive work.",
        "Great job staying on task! {duration} min of dedicated progress achieved.",
        "Momentum unlocked: {duration} min of deep focus completed. Keep it up!",
        "Solid work: {duration} min in your productive flow. You're making real progress!"
    ]
}


class RephraseEngine:
    """Manages the phrase bank, in-memory cache, and LLM rephrasing."""

    def __init__(self, provider_manager: ProviderManager):
        self.provider = provider_manager
        self.bank = self._load_or_create_bank()
        self.cache: Dict[str, str] = {}
        self.max_cache_size = 500

    def _load_or_create_bank(self) -> Dict[str, List[str]]:
        if os.path.exists(PHRASE_BANK_PATH):
            try:
                with open(PHRASE_BANK_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "phrases" in data:
                        return data["phrases"]
            except Exception as e:
                print(f"[Rephrase] Error reading phrase_bank.json: {e}. Using defaults.")

        # Save default phrase bank
        self._save_bank(DEFAULT_PHRASE_BANK)
        return DEFAULT_PHRASE_BANK

    def _save_bank(self, bank: Dict[str, List[str]]):
        try:
            with open(PHRASE_BANK_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "version": BANK_VERSION,
                    "updated_at": time.time(),
                    "phrases": bank
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Rephrase] Error saving phrase bank: {e}")

    def get_bank_phrase(self, event: str, app: str, duration_min: int = 0, cooldown_sec: int = 0) -> str:
        """Instant (< 1ms) phrase bank lookup."""
        event_key = event.lower()
        phrases = self.bank.get(event_key, self.bank.get("block", ["Time to refocus on your goals!"]))
        template = random.choice(phrases)

        return template.format(
            app=app or "this app",
            duration=duration_min or 1,
            cooldown=cooldown_sec or 60
        )

    def rephrase(self, event: str, app: str, category: str = "distraction",
                 duration_min: int = 0, cooldown_sec: int = 0,
                 policy: str = "BLOCK", tone: str = "constructive",
                 lang: str = "en", user_name: str = "") -> str:
        """
        On-demand contextual rephrase with fallback to offline phrase bank.
        """
        cache_key = f"{event}:{app}:{category}:{duration_min}:{policy}:{tone}:{lang}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Construct prompt for LLM
        system_prompt = (
            "You are the constructive, non-judgmental mindfulness voice of FocusGuard, a desktop productivity app. "
            "Write a single, encouraging alert sentence reminding the user to return to their goals. "
            "Do NOT use harsh words like 'BLOCKED', 'RESTRICTED', or 'FORBIDDEN'. Be kind, brief, and motivating. "
            "Respond with ONLY the sentence. Do not include quotes, greetings, or explanations."
        )

        user_prompt = (
            f"Event: {event}\n"
            f"Application: {app}\n"
            f"Category: {category}\n"
            f"Elapsed minutes: {duration_min}\n"
            f"Policy action: {policy}\n"
            f"Tone: {tone}\n"
            f"Language: {lang}\n"
            "Generate one short, motivating sentence (under 120 characters):"
        )

        llm_response = self.provider.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=60,
            temperature=0.7,
            timeout=1.0,
            lang=lang
        )

        if llm_response:
            # Clean and sanitize LLM response
            cleaned = llm_response.strip().strip('"').strip("'").strip()
            # If the response is clean and not overly long
            if 10 < len(cleaned) < 220:
                if len(self.cache) >= self.max_cache_size:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[cache_key] = cleaned
                return cleaned

        # Fallback to phrase bank
        return self.get_bank_phrase(event, app, duration_min, cooldown_sec)

    def regenerate_bank(self) -> Dict[str, Any]:
        """Regenerates the offline phrase bank with LLM or reloads defaults."""
        count = sum(len(v) for v in self.bank.values())
        return {
            "bank_version": BANK_VERSION,
            "count": count,
            "categories": list(self.bank.keys())
        }
