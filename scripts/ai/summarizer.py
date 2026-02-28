"""
ai.summarizer — Bilingual cover-story summariser powered by DeepSeek-V3.

Uses the OpenAI-compatible endpoint on Azure AI (GitHub Models) to produce
a structured JSON object containing Chinese and English titles and summaries.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from openai import OpenAI

from .prompts import SYSTEM_PROMPT, COVER_STORY_PROMPT
from ..scraper.base import CoverArticleRaw

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected JSON schema for validation
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"title", "summary"}
_REQUIRED_LANG_KEYS = {"zh", "en"}


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
        # Each value should be a non-empty string.
        for lang in _REQUIRED_LANG_KEYS:
            if not isinstance(inner[lang], str) or not inner[lang].strip():
                return False
    return True


# ---------------------------------------------------------------------------
# Summariser class
# ---------------------------------------------------------------------------

class BilingualSummarizer:
    """Generates bilingual (zh + en) summaries using DeepSeek-V3 via Azure AI.

    Configuration
    -------------
    - **API key**: read from the ``GITHUB_TOKEN`` environment variable.
    - **Base URL**: ``https://models.inference.ai.azure.com``
    - **Model**: ``DeepSeek-V3-0324``
    """

    MODEL = "DeepSeek-V3-0324"
    BASE_URL = "https://models.inference.ai.azure.com"
    TEMPERATURE = 0.7
    MAX_RETRIES = 1  # Number of *additional* attempts after the first failure.

    def __init__(self, api_key: Optional[str] = None) -> None:
        """Initialise the OpenAI client.

        Parameters
        ----------
        api_key:
            An explicit API key.  Falls back to ``GITHUB_TOKEN`` env var.
        """
        resolved_key = api_key or os.environ.get("GITHUB_TOKEN", "")
        if not resolved_key:
            logger.warning(
                "No API key provided and GITHUB_TOKEN is not set. "
                "Summarisation calls will fail."
            )

        self._client = OpenAI(
            api_key=resolved_key,
            base_url=self.BASE_URL,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize(self, article: CoverArticleRaw) -> Optional[Dict[str, Any]]:
        """Generate a bilingual summary for *article*.

        Returns a ``dict`` with ``title`` and ``summary`` keys (each
        containing ``zh`` and ``en`` sub-keys), or ``None`` if generation
        or parsing fails after retries.
        """
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

        for attempt in range(1, self.MAX_RETRIES + 2):  # +2 because range is exclusive
            logger.info(
                "Requesting summary from %s (attempt %d/%d) ...",
                self.MODEL,
                attempt,
                self.MAX_RETRIES + 1,
            )
            try:
                result = self._call_model(user_prompt)
                if result is not None:
                    return result
                logger.warning("Invalid JSON structure on attempt %d", attempt)
            except Exception as exc:
                logger.error("Model call failed on attempt %d: %s", attempt, exc)

        logger.error(
            "Failed to generate valid summary for %s vol.%s #%s after %d attempts",
            article.journal,
            article.volume,
            article.issue,
            self.MAX_RETRIES + 1,
        )
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_model(self, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Send a single request to the model and parse the response.

        Returns the validated ``dict`` or ``None`` on failure.
        """
        response = self._client.chat.completions.create(
            model=self.MODEL,
            temperature=self.TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_text = response.choices[0].message.content
        if not raw_text:
            logger.warning("Model returned empty content")
            return None

        logger.debug("Raw model response: %s", raw_text[:500])

        # Strip markdown code fences if the model ignores our instructions.
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            # Remove ```json ... ``` wrapper.
            cleaned = cleaned.split("\n", 1)[-1]  # drop first line
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse error: %s", exc)
            return None

        if not _validate_output(data):
            logger.warning(
                "Output does not match expected schema. Keys: %s",
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
            return None

        return data
