"""
ai.summarizer — Bilingual cover-story summariser with multi-backend fallback.

Uses the OpenAI-compatible endpoint on OpenRouter (and Google Gemini) to
produce a structured JSON object containing Chinese and English titles and
summaries.

Supports two modes:
  - **Abstract-only**: 2–4 paragraph free-form summary (original mode).
  - **Full-text**: Structured 4-part summary (總結/問題/方法/結果) when the
    full article text is available via preprints or open-access pages.

Backend fallback
----------------
Multiple API backends are tried in priority order.  When one backend returns
a 402 (insufficient credits / quota exhausted), the next backend is tried
automatically.  Configure backends via environment variables — any backend
whose key env-var is empty or missing is silently skipped.

Priority order:
  1. gemini-2.0-flash                  (GEMINI_API_KEY            — Google)
  2. z-ai/glm-4.5-air:free             (OPENROUTER_KEY_GLAI       — OpenRouter)
  3. nvidia/nemotron-3-nano-30b-a3b:free (OPENROUTER_KEY_NVIDIA   — OpenRouter)
  4. qwen/qwen3-next-80b-a3b-instruct:free (OPENROUTER_KEY_QWEN3  — OpenRouter)
  5. minimax/minimax-m2.5:free         (OPENROUTER_KEY_MINIMAX    — OpenRouter)
  6. openrouter/auto                   (OPENROUTER_FREE_API_KEY   — OpenRouter auto free routing)
  7. deepseek-chat                     (DEEPSEEK_API_KEY          — DeepSeek, PAID, last resort)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from .prompts import SYSTEM_PROMPT, COVER_STORY_PROMPT, COVER_STORY_FULLTEXT_PROMPT
from ..scraper.base import CoverArticleRaw

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected JSON schema for validation
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"title", "summary"}
_REQUIRED_LANG_KEYS = {"zh", "en"}

# Maximum characters of full text to include in the summariser prompt.
_MAX_FULLTEXT_CHARS = int(os.environ.get("SUMMARIZER_MAX_FULLTEXT_CHARS", "60000"))

# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

# Each tuple: (env_var_name, model_id, base_url)
# Tried in this priority order; 402/404/PerDay causes fallover to the next entry.
# Order is based on observed reliability: glm-4.5-air and nvidia tend to be
# available; qwen3 is often upstream-rate-limited from Venice provider.
_BACKEND_CONFIGS: List[Tuple[str, str, str]] = [
    (
        "GEMINI_API_KEY",
        "gemini-2.0-flash",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    (
        "OPENROUTER_KEY_GLAI",
        "z-ai/glm-4.5-air:free",
        "https://openrouter.ai/api/v1",
    ),
    (
        "OPENROUTER_KEY_NVIDIA",
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "https://openrouter.ai/api/v1",
    ),
    (
        "OPENROUTER_KEY_QWEN3",
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "https://openrouter.ai/api/v1",
    ),
    (
        "OPENROUTER_KEY_MINIMAX",
        "minimax/minimax-m2.5:free",
        "https://openrouter.ai/api/v1",
    ),
    # Free auto-routing key — OpenRouter picks the best available free model.
    (
        "OPENROUTER_FREE_API_KEY",
        "openrouter/auto",
        "https://openrouter.ai/api/v1",
    ),
    # PAID fallback — only reached when every free backend above has failed.
    (
        "DEEPSEEK_API_KEY",
        "deepseek-v4-flash",
        "https://api.deepseek.com",
    ),
]

_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/lch99310/SciCover_Summary",
    "X-Title": "SciCover Summary",
}


def _build_backends() -> List[Tuple[OpenAI, str]]:
    """Build the list of (client, model) pairs from available env vars.

    Backends whose key env-var is empty or absent are skipped silently.
    """
    backends: List[Tuple[OpenAI, str]] = []
    for env_var, model, base_url in _BACKEND_CONFIGS:
        key = os.environ.get(env_var, "").strip()
        if not key:
            continue
        # Google's Gemini endpoint doesn't need the OpenRouter custom headers.
        headers = _OPENROUTER_HEADERS if "openrouter" in base_url else {}
        client = OpenAI(
            api_key=key,
            base_url=base_url,
            default_headers=headers,
        )
        backends.append((client, model))
        logger.debug("Registered backend: %s (env: %s)", model, env_var)
    return backends


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def _validate_output(data: Any) -> bool:
    """Return ``True`` if *data* conforms to the expected schema."""
    if not isinstance(data, dict):
        return False
    if not _REQUIRED_KEYS.issubset(data.keys()):
        return False
    for key in _REQUIRED_KEYS:
        inner = data.get(key)
        if not isinstance(inner, dict):
            return False
        if not _REQUIRED_LANG_KEYS.issubset(inner.keys()):
            return False
        for lang in _REQUIRED_LANG_KEYS:
            if not isinstance(inner[lang], str) or not inner[lang].strip():
                return False
    return True


# ---------------------------------------------------------------------------
# Summariser class
# ---------------------------------------------------------------------------

class BilingualSummarizer:
    """Generates bilingual (zh + en) summaries with multi-backend fallback.

    Backends are tried in the order defined in ``_BACKEND_CONFIGS``.  A 402
    (insufficient credits) response causes immediate fallover to the next
    backend.  Other errors trigger per-backend retries before falling over.
    """

    TEMPERATURE = 0.7
    MAX_RETRIES = 2  # Additional attempts per backend before giving up on it.

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._backends = _build_backends()

        if not self._backends:
            logger.warning(
                "No API keys found for any backend. Summarisation calls will fail."
            )
        else:
            models = [m for _, m in self._backends]
            logger.info("Summariser backends (in priority order): %s", models)

        self._last_mode = "abstract-only"
        # Models that exhausted all retries due to 429 rate limits in this
        # session are blacklisted so subsequent articles skip them immediately.
        self._rate_limit_blacklist: set = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize(
        self,
        article: CoverArticleRaw,
        fulltext: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate a bilingual summary for *article*.

        Tries full-text mode first (if text is available), then falls back
        to abstract-only.  Within each mode, all registered backends are
        tried in priority order before giving up.
        """
        self._last_mode = "abstract-only"

        if fulltext:
            truncated = self._truncate_fulltext(fulltext)
            if len(truncated) < len(fulltext):
                logger.info(
                    "Truncated full text from %d to %d chars for model input",
                    len(fulltext), len(truncated),
                )
            result = self._try_mode("full-text", article, fulltext=truncated)
            if result is not None:
                self._last_mode = "full-text"
                return result
            logger.warning(
                "Full-text summary failed for %s — falling back to abstract-only mode",
                article.journal,
            )

        result = self._try_mode("abstract-only", article, fulltext=None)
        if result is not None:
            self._last_mode = "abstract-only"
            return result

        logger.error(
            "Failed to generate valid summary for %s vol.%s #%s",
            article.journal,
            article.volume,
            article.issue,
        )
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_mode(
        self,
        mode: str,
        article: CoverArticleRaw,
        fulltext: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Attempt summarisation in the given *mode*, cycling through backends."""
        if mode == "full-text" and fulltext:
            user_prompt = COVER_STORY_FULLTEXT_PROMPT.format(
                journal=article.journal,
                volume=article.volume or "—",
                issue=article.issue or "—",
                date=article.date or "—",
                cover_description=article.cover_description or "(not available)",
                article_title=article.article_title or "(not available)",
                authors=", ".join(article.article_authors) if article.article_authors else "(not available)",
                fulltext=fulltext,
            )
        else:
            user_prompt = COVER_STORY_PROMPT.format(
                journal=article.journal,
                volume=article.volume or "—",
                issue=article.issue or "—",
                date=article.date or "—",
                cover_description=article.cover_description or "(not available)",
                article_title=article.article_title or "(not available)",
                authors=", ".join(article.article_authors) if article.article_authors else "(not available)",
                abstract=article.article_abstract or "(not available)",
            )

        for client, model in self._backends:
            if model in self._rate_limit_blacklist:
                logger.info(
                    "[%s] Skipping — persistently rate-limited earlier in this session",
                    model,
                )
                continue
            result = self._try_backend(mode, client, model, user_prompt)
            if result is not None:
                return result

        return None

    def _try_backend(
        self,
        mode: str,
        client: OpenAI,
        model: str,
        user_prompt: str,
    ) -> Optional[Dict[str, Any]]:
        """Try one backend with retries.  Returns result or None on failure.

        If ALL attempts fail due to 429 rate limits, the model is added to
        ``self._rate_limit_blacklist`` so subsequent articles skip it.
        """
        rate_limit_failures = 0
        for attempt in range(1, self.MAX_RETRIES + 2):
            logger.info(
                "Requesting %s summary from %s (attempt %d/%d) ...",
                mode,
                model,
                attempt,
                self.MAX_RETRIES + 1,
            )
            try:
                result = self._call_model(client, model, user_prompt)
                if result is not None:
                    return result
                logger.warning(
                    "[%s] Invalid JSON structure on attempt %d", model, attempt
                )
            except Exception as exc:
                exc_str = str(exc)
                logger.error(
                    "[%s] Model call failed on attempt %d: %s", model, attempt, exc
                )

                # 402 — insufficient credits: skip this backend immediately.
                if "402" in exc_str or "credits" in exc_str.lower() or "afford" in exc_str.lower():
                    logger.warning(
                        "[%s] Insufficient credits — switching to next backend", model
                    )
                    return None

                # 404 — endpoint not available (e.g. guardrail/data-policy
                # restrictions on OpenRouter).  This is a permanent config
                # issue, not a transient error — skip immediately.
                if "404" in exc_str:
                    logger.warning(
                        "[%s] Endpoint not available (404) — switching to next backend",
                        model,
                    )
                    return None

                # 413 — request too large: no point retrying the same prompt.
                if "413" in exc_str or "too large" in exc_str.lower():
                    logger.warning(
                        "[%s] Request too large — aborting retries for %s mode",
                        model, mode,
                    )
                    return None

                # 429 / RESOURCE_EXHAUSTED — rate limited.
                if "429" in exc_str or "rate" in exc_str.lower() or "RESOURCE_EXHAUSTED" in exc_str:
                    # Daily quota exhaustion: retrying later is pointless.
                    if "PerDay" in exc_str or "per_day" in exc_str or "daily" in exc_str.lower():
                        logger.warning(
                            "[%s] Daily quota exhausted — switching to next backend",
                            model,
                        )
                        return None
                    # Per-minute / upstream rate limit: count and retry.
                    rate_limit_failures += 1
                    wait = self._extract_retry_wait(exc_str)
                    if attempt < self.MAX_RETRIES + 1:
                        logger.info(
                            "[%s] Rate limited — waiting %d s before retry",
                            model, wait,
                        )
                        time.sleep(wait)
                    continue

        # If every attempt was a rate-limit failure, blacklist for this session.
        if rate_limit_failures >= self.MAX_RETRIES + 1:
            self._rate_limit_blacklist.add(model)
            logger.warning(
                "[%s] All %d attempts rate-limited — blacklisting for this session",
                model, rate_limit_failures,
            )

        return None

    @staticmethod
    def _truncate_fulltext(text: str) -> str:
        """Truncate full text to fit within the model's input token budget."""
        if len(text) <= _MAX_FULLTEXT_CHARS:
            return text
        cut = text[:_MAX_FULLTEXT_CHARS].rfind("\n\n")
        if cut > _MAX_FULLTEXT_CHARS * 0.8:
            return text[:cut].rstrip()
        return text[:_MAX_FULLTEXT_CHARS].rstrip()

    @staticmethod
    def _extract_retry_wait(error_msg: str) -> int:
        """Parse the number of seconds to wait from a rate-limit error message.

        Handles multiple formats:
          - Gemini: "Please retry in 43.967456436s."
          - Gemini JSON: "'retryDelay': '43s'"
          - Generic: "wait/retry ... N seconds"
        """
        # Gemini: "retry in 43.967s" or "retry in 43s"
        match = re.search(r"retry\s+in\s+(\d+)(?:\.\d+)?s", error_msg, re.I)
        if match:
            return min(int(match.group(1)) + 2, 120)
        # Gemini JSON field: retryDelay: '43s'
        match = re.search(r"retryDelay['\": ]+(\d+)s", error_msg, re.I)
        if match:
            return min(int(match.group(1)) + 2, 120)
        # Generic: "wait N seconds" / "retry after N seconds"
        match = re.search(r"(?:wait|retry.*?)\s+(\d+)\s*seconds?", error_msg, re.I)
        if match:
            return min(int(match.group(1)) + 2, 120)
        return 45  # conservative default

    def _call_model(
        self,
        client: OpenAI,
        model: str,
        user_prompt: str,
    ) -> Optional[Dict[str, Any]]:
        """Send a single request to *model* via *client* and parse the response."""
        response = client.chat.completions.create(
            model=model,
            temperature=self.TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            logger.warning("[%s] Model returned empty content", model)
            return None

        logger.debug("[%s] Raw response: %s", model, raw_text[:500])

        # Strip <think>...</think> blocks from reasoning/thinking models.
        cleaned = re.sub(
            r"<think>.*?</think>", "", raw_text, flags=re.DOTALL
        ).strip()

        # Strip markdown code fences if the model ignores our instructions.
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("[%s] JSON parse error: %s", model, exc)
            return None

        if not _validate_output(data):
            logger.warning(
                "[%s] Output does not match expected schema. Keys: %s",
                model,
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
            return None

        return data
