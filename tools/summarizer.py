"""
FocusGuard Daily and Weekly Focus Summarizer
Aggregates activity tracking and generates natural-language insights and suggestions.
"""

import json
from typing import Dict, Any, List, Optional
from llm_provider import ProviderManager


class FocusSummarizer:
    def __init__(self, provider_manager: ProviderManager):
        self.provider = provider_manager
        self.daily_cache: Dict[str, Dict[str, Any]] = {}

    def generate_daily_summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a natural-language report from daily activity tracking."""
        date_str = data.get("date", "today")
        prod_sec = data.get("productive_seconds", 0)
        dist_sec = data.get("distraction_seconds", 0)
        neut_sec = data.get("neutral_seconds", 0)
        app_breakdown = data.get("app_breakdown", {})
        blocks_count = data.get("blocks_count", 0)

        total_tracked = prod_sec + dist_sec + neut_sec
        prod_min = prod_sec // 60
        dist_min = dist_sec // 60
        prod_ratio = int((prod_sec / total_tracked * 100)) if total_tracked > 0 else 0

        # Sort top apps
        sorted_apps = sorted(app_breakdown.items(), key=lambda x: x[1], reverse=True)
        top_apps_str = ", ".join([f"{k} ({v // 60}m)" for k, v in sorted_apps[:5]]) or "None tracked"

        system_prompt = (
            "You are FocusGuard's analytics assistant. Analyze the user's daily desktop productivity stats. "
            "Write a brief, motivating summary (2-3 sentences), 2 key insights, and 2 actionable suggestions. "
            "Respond ONLY with valid JSON in this exact structure:\n"
            "{\n"
            '  "summary": "...",\n'
            '  "insights": ["...", "..."],\n'
            '  "suggestions": ["...", "..."]\n'
            "}"
        )

        user_prompt = (
            f"Date: {date_str}\n"
            f"Productive Time: {prod_min} minutes ({prod_ratio}%)\n"
            f"Distraction Time: {dist_min} minutes\n"
            f"Restricted App Blocks: {blocks_count}\n"
            f"Top Apps: {top_apps_str}\n"
        )

        llm_response = self.provider.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=300,
            temperature=0.7,
            timeout=3.0
        )

        if llm_response:
            try:
                # Extract JSON using regex
                import re
                match = re.search(r"\{[\s\S]*\}", llm_response)
                if match:
                    res = json.loads(match.group(0))
                    if "summary" in res and "suggestions" in res:
                        self.daily_cache[date_str] = res
                        return res
            except Exception:
                pass

        # Fallback summary if LLM is offline
        fallback_summary = (
            f"On {date_str}, you logged {prod_min} minutes of productive work ({prod_ratio}% of active time). "
            f"Distractions accounted for {dist_min} minutes across {blocks_count} blocked interventions."
        )
        fallback_insights = [
            f"Top active tools: {top_apps_str}",
            f"Interventions prevented {blocks_count} prolonged distraction sessions."
        ]
        fallback_suggestions = [
            "Consider setting a CONTENT_AWARE policy on video platforms to keep tutorials open while blocking Shorts.",
            "Take a short 5-minute stretch break every 60 minutes to maintain high cognitive focus."
        ]

        result = {
            "summary": fallback_summary,
            "insights": fallback_insights,
            "suggestions": fallback_suggestions
        }
        self.daily_cache[date_str] = result
        return result
