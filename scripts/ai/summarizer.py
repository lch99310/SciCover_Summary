"""
ai.summarizer — Bilingual cover-story summariser powered by Qwen3 VL via OpenRouter.

Uses the OpenAI-compatible endpoint on OpenRouter to produce a structured
JSON object containing Chinese and English titles and summaries.

Supports two modes:
  - **Abstract-only**: 2–4 paragraph free-form summary (original mode).
  - **Full-text**: Structured 4-part summary (總結/問題/方法/結果) when the
    full article text is available via preprints or open-access pages.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
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
# Qwen3 VL 30B A3B Thinking has a 131 072-token context window, so we can
# comfortably accommodate the full article text fetched by fulltext.py
# (capped at 60 000 chars there).  Override via environment variable.
_MAX_FULLTEXT_CHARS = int(os.environ.get("SUMMARIZER_MAX_FULLTEXT_CHARS", "60000"))


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
    """Generates bilingual (zh + en) summaries using Qwen3 VL via OpenRouter.

    Configuration
    -------------
    - **API key**: read from ``MODELS_PAT_QWEN3_VL_30B`` environment variable,
      falling back to ``GITHUB_TOKEN``.
    - **Base URL**: ``https://openrouter.ai/api/v1``
    - **Model**: ``qwen/qwen3-vl-30b-a3b-thinking`` (131K context window)
    """

    MODEL = os.environ.get(
        "SUMMARIZER_MODEL", "qwen/qwen3-vl-30b-a3b-thinking"
    )
    BASE_URL = os.environ.get(
        "SUMMARIZER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    TEMPERATURE = 0.7
    MAX_RETRIES = 2  # Number of *additional* attempts after the first failure.

    def __init__(self, api_key: Optional[str] = None) -> None:
        """Initialise the OpenAI client.

        Parameters
        ----------
        api_key:
            An explicit API key.  Falls back to ``MODELS_PAT_QWEN3_VL_30B``
            or ``GITHUB_TOKEN`` env vars.
        """
        resolved_key = (
            api_key
            or os.environ.get("MODELS_PAT_QWEN3_VL_30B", "")
            or os.environ.get("GITHUB_TOKEN", "")
        )
        if not resolved_key:
            logger.warning(
                "No API key provided (checked MODELS_PAT_QWEN3_VL_30B and "
                "GITHUB_TOKEN). Summarisation calls will fail."
            )

        self._client = OpenAI(
            api_key=resolved_key,
            base_url=self.BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/lch99310/SciCover_Summary",
                "X-Title": "SciCover Summary",
            },
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
                exc_str = str(exc)
                logger.error("Model call failed on attempt %d: %s", attempt, exc)
                # If the request body is too large, no point retrying the
                # same prompt — break immediately so the caller can fall
                # back to a shorter prompt (abstract-only mode).
                if "413" in exc_str or "too large" in exc_str.lower():
                    logger.warning(
                        "Request too large — aborting retries for %s mode",
                        mode,
                    )
                    break
                # Rate limit: extract wait time from the error message and
                # sleep before retrying.
                if "429" in exc_str or "rate" in exc_str.lower():
                    wait = self._extract_retry_wait(exc_str)
                    if attempt < self.MAX_RETRIES + 1:
                        logger.info(
                            "Rate limited — waiting %d seconds before retry",
                            wait,
                        )
                        time.sleep(wait)
                    continue

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
        """Parse the number of seconds to wait from a rate-limit error message."""
        match = re.search(r"(?:wait|retry.*?)\s+(\d+)\s*seconds?", error_msg, re.I)
        if match:
            return min(int(match.group(1)) + 2, 120)  # cap at 2 min, add buffer
        return 65  # default: slightly over 1 minute

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

        # Strip <think>...</think> blocks from reasoning/thinking models.
        cleaned = re.sub(
            r"<think>.*?</think>", "", raw_text, flags=re.DOTALL
        ).strip()

        # Strip markdown code fences if the model ignores our instructions.
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
