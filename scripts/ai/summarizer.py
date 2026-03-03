"""
ai.summarizer — Bilingual cover-story summariser powered by DeepSeek-V3.

Uses the OpenAI-compatible endpoint on Azure AI (GitHub Models) to produce
a structured JSON object containing Chinese and English titles and summaries.

Supports two modes:
  - **Abstract-only**: 2–4 paragraph free-form summary (original mode).
  - **Full-text**: Structured 4-part summary (總結/問題/方法/結果) when the
    full article text is available via preprints or open-access pages.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

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
# GitHub Models free tier limits DeepSeek-V3 to ~4 000 input tokens;
# reserving ~800 tokens for the system/template overhead leaves ~3 200
# tokens for article content.  At ~4 chars/token that is ~12 800 chars;
# we use 8 000 as a safe default.  Override via environment variable.
_MAX_FULLTEXT_CHARS = int(os.environ.get("SUMMARIZER_MAX_FULLTEXT_CHARS", "8000"))


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
        resolved_key = (
            api_key
            or os.environ.get("MODELS_PAT_DEEPSEEK_V3", "")
            or os.environ.get("GITHUB_TOKEN", "")
        )
        if not resolved_key:
            logger.warning(
                "No API key provided (checked MODELS_PAT_DEEPSEEK_V3 and "
                "GITHUB_TOKEN). Summarisation calls will fail."
            )

        self._client = OpenAI(
            api_key=resolved_key,
            base_url=self.BASE_URL,
        )
        self._last_mode = "abstract-only"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize(
        self,
        article: CoverArticleRaw,
        fulltext: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate a bilingual summary for *article*.

        Parameters
        ----------
        article:
            The scraped article metadata (title, abstract, etc.).
        fulltext:
            Optional full-text content.  When provided, the summariser
            uses the structured 4-part prompt (總結/問題/方法/結果).
            When ``None``, falls back to the abstract-only prompt.

        Returns a ``dict`` with ``title`` and ``summary`` keys (each
        containing ``zh`` and ``en`` sub-keys), or ``None`` if generation
        or parsing fails after retries.

        If full-text mode fails (e.g. due to token limits), the method
        automatically falls back to abstract-only mode.  The actual mode
        used is stored in ``self._last_mode``.
        """
        self._last_mode = "abstract-only"

        # --- Try full-text mode first (if text available) ---
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
                "Full-text summary failed for %s — falling back to "
                "abstract-only mode",
                article.journal,
            )

        # --- Abstract-only mode (primary or fallback) ---
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
        """Attempt summarisation in the given *mode* with retries."""
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

        for attempt in range(1, self.MAX_RETRIES + 2):
            logger.info(
                "Requesting %s summary from %s (attempt %d/%d) ...",
                mode,
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
                # If the request body is too large, no point retrying the
                # same prompt — break immediately so the caller can fall
                # back to a shorter prompt (abstract-only mode).
                if "413" in str(exc) or "too large" in str(exc).lower():
                    logger.warning(
                        "Request too large — aborting retries for %s mode",
                        mode,
                    )
                    break

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
