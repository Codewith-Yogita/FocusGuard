"""
FocusGuard Unified LLM Provider Abstraction
Handles local Ollama (Qwen 2.5), cloud Groq, and Sarvam (Indic) with circuit-breaking and privacy redaction.
"""

import os
import time
import re
import urllib.parse
from typing import Optional, Dict, Any, List
import requests

def load_env_file():
    """Lightweight .env loader that populates os.environ without requiring external packages."""
    search_dirs = [
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ]
    for d in search_dirs:
        env_path = os.path.join(d, ".env")
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k not in os.environ:
                                os.environ[k] = v
                break
            except Exception:
                pass

load_env_file()

# Default endpoints and models
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "qwen2.5vl:3b"
DEFAULT_GROQ_MODEL = os.environ.get("GROQ_MODEL", "groq/compound-mini")
DEFAULT_SARVAM_MODEL = os.environ.get("SARVAM_MODEL", "sarvam-2b")

CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 60.0


def redact_url_to_domain(url: str) -> str:
    """Redacts full URL to domain only to protect user privacy before cloud API calls."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc or parsed.path
        # Remove port if present
        domain = netloc.split(":")[0]
        # Remove www prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


class CircuitBreaker:
    """Simple circuit breaker to avoid hanging on failing providers."""

    def __init__(self, failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD, cooldown: float = CIRCUIT_COOLDOWN_SECONDS):
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.failure_count = 0
        self.last_failure_time = 0.0

    def is_available(self) -> bool:
        if self.failure_count >= self.failure_threshold:
            if time.time() - self.last_failure_time > self.cooldown:
                # Reset to half-open
                self.failure_count = 0
                return True
            return False
        return True

    def record_success(self):
        self.failure_count = 0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()


class BaseProvider:
    def __init__(self, name: str):
        self.name = name
        self.circuit = CircuitBreaker()

    def is_configured(self) -> bool:
        return True

    def generate(self, prompt: str, system_prompt: str = "", max_tokens: int = 150, temperature: float = 0.7, timeout: float = 2.0) -> Optional[str]:
        raise NotImplementedError


class OllamaProvider(BaseProvider):
    def __init__(self, url: str = DEFAULT_OLLAMA_URL, model: str = DEFAULT_OLLAMA_MODEL):
        super().__init__("ollama")
        self.url = url
        self.model = model

    def generate(self, prompt: str, system_prompt: str = "", max_tokens: int = 150, temperature: float = 0.7, timeout: float = 2.0) -> Optional[str]:
        if not self.circuit.is_available():
            return None

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }

        try:
            resp = requests.post(self.url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                self.circuit.record_success()
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
            self.circuit.record_failure()
            return None
        except Exception:
            self.circuit.record_failure()
            return None


class GroqProvider(BaseProvider):
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_GROQ_MODEL):
        super().__init__("groq")
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, system_prompt: str = "", max_tokens: int = 150, temperature: float = 0.7, timeout: float = 2.0) -> Optional[str]:
        if not self.is_configured() or not self.circuit.is_available():
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        try:
            resp = requests.post(self.url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                self.circuit.record_success()
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
            self.circuit.record_failure()
            return None
        except Exception:
            self.circuit.record_failure()
            return None


class SarvamProvider(BaseProvider):
    """Optional Indic language provider for Hindi and regional rephrasing."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_SARVAM_MODEL):
        super().__init__("sarvam")
        self.api_key = api_key or os.environ.get("SARVAM_API_KEY", "")
        self.model = model
        self.url = "https://api.sarvam.ai/v1/chat/completions"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, system_prompt: str = "", max_tokens: int = 150, temperature: float = 0.7, timeout: float = 2.0) -> Optional[str]:
        if not self.is_configured() or not self.circuit.is_available():
            return None

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        try:
            resp = requests.post(self.url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                self.circuit.record_success()
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
            self.circuit.record_failure()
            return None
        except Exception:
            self.circuit.record_failure()
            return None


class ProviderManager:
    """Manages the fallback chain: Ollama -> Groq -> Sarvam."""

    def __init__(self, ollama_url: str = DEFAULT_OLLAMA_URL, ollama_model: str = DEFAULT_OLLAMA_MODEL):
        self.ollama = OllamaProvider(url=ollama_url, model=ollama_model)
        self.groq = GroqProvider()
        self.sarvam = SarvamProvider()

    def generate(self, prompt: str, system_prompt: str = "", max_tokens: int = 150, temperature: float = 0.7, timeout: float = 1.5, lang: str = "en") -> Optional[str]:
        # 1. Indic languages preference if Sarvam is configured
        if lang in ("hi", "indic") and self.sarvam.is_configured() and self.sarvam.circuit.is_available():
            res = self.sarvam.generate(prompt, system_prompt, max_tokens, temperature, timeout)
            if res:
                return res

        # 2. Local Ollama (Primary)
        if self.ollama.circuit.is_available():
            res = self.ollama.generate(prompt, system_prompt, max_tokens, temperature, timeout)
            if res:
                return res

        # 3. Cloud Groq Fallback
        if self.groq.is_configured() and self.groq.circuit.is_available():
            res = self.groq.generate(prompt, system_prompt, max_tokens, temperature, timeout)
            if res:
                return res

        return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "ollama_available": self.ollama.circuit.is_available(),
            "groq_configured": self.groq.is_configured(),
            "groq_available": self.groq.circuit.is_available(),
            "sarvam_configured": self.sarvam.is_configured(),
            "sarvam_available": self.sarvam.circuit.is_available(),
            "active_primary": "ollama" if self.ollama.circuit.is_available() else ("groq" if self.groq.is_configured() and self.groq.circuit.is_available() else "offline_bank")
        }
