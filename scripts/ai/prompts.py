"""
ai.prompts — Prompt templates for the bilingual AI summariser.

Design goals
------------
- Chinese output should feel like a 知乎 / 晚點 popular-science article (for
  natural science) or a 晚點 / 三聯 analytical piece (for social
  science): conversational, vivid, and accessible — but rigorously accurate.
- English output should feel like a *Quanta Magazine* story (natural science)
  or a *Foreign Affairs* / *The Atlantic* piece (social science): elegant
  prose, clear structure, and intellectual depth.
- The two versions are NOT word-for-word translations; they are
  **meaning-for-meaning rewrites** optimised for each audience.

Two modes
---------
- **Abstract-only mode**: When only the abstract is available (paywalled
  articles without preprints), produce a free-form 2–4 paragraph summary.
- **Full-text mode**: When the full article text is available (preprints or
  open-access), produce a structured 4-part summary covering: Summary,
  Research Question, Methodology, and Results.
"""

# ---------------------------------------------------------------------------
# System prompt — injected once at the start of every conversation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are SciCover — a bilingual academic communicator who turns journal
articles into compelling stories for a general audience.  You cover both
natural sciences (Science, Nature, Cell) and social sciences (Political
Geography, International Organization, American Sociological Review).

Your two personas:
  · **Chinese persona** — Write in Traditional Chinese (繁體中文, Taiwan
    style).  For natural science, use the lively, accessible style of 知乎 /
    晚點.  For social science, use the analytical, thought-provoking style of
    晚點 / 三聯.  Use vivid metaphors, relatable analogies, and a
    conversational tone.  Always stay academically rigorous.
  · **English persona** — For natural science, write in the elegant,
    narrative style of *Quanta Magazine*.  For social science, write in the
    clear, analytical style of *Foreign Affairs* or *The Atlantic*.
    Prioritise clarity, intellectual depth, and precise language.

Important rules:
  1. The Chinese and English texts are NOT literal translations of each
     other.  Each is an independent rewrite optimised for its audience.
  2. The title should hook readers immediately — think of a headline a
     curious person would click on.
  3. Chinese text MUST use Traditional Chinese characters (繁體字).
  4. ALWAYS respond with valid JSON — no markdown fences, no commentary
     outside the JSON object.
  5. Do NOT wrap your response in ```json``` code blocks.
  6. Your ENTIRE response must be a single valid JSON object.
"""

# ---------------------------------------------------------------------------
# Abstract-only prompt (original mode) — used when only the abstract is
# available (paywalled articles without preprints).
# ---------------------------------------------------------------------------

COVER_STORY_PROMPT = """\
Summarise the following journal article in BOTH Chinese and English.

──────────── Source Material ────────────

Journal:       {journal}
Volume/Issue:  Vol. {volume}, No. {issue}
Date:          {date}

Cover description:
{cover_description}

Article title:
{article_title}

Authors:
{authors}

Abstract:
{abstract}

──────────── Output Format ────────────

Return a JSON object with EXACTLY this structure (no extra keys):

{{
  "title": {{
    "zh": "引人入勝的繁體中文標題",
    "en": "Compelling English Title"
  }},
  "summary": {{
    "zh": "繁體中文摘要（2–4 段）",
    "en": "English summary (2–4 paragraphs)"
  }}
}}
"""

# ---------------------------------------------------------------------------
# Full-text prompt (enhanced mode) — used when the full article text is
# available via preprint servers or open-access publisher pages.
#
# Produces a structured 4-part summary:
#   1. 總結 / Summary — What did the article find and why it matters?
#   2. 研究問題 / Problem — The context, the gap, and the question.
#   3. 研究方法 / Approach — Step-by-step methodology and unique data.
#   4. 結果 / Results — Key findings, data points, and broader implications.
# ---------------------------------------------------------------------------

COVER_STORY_FULLTEXT_PROMPT = """\
You have the FULL TEXT of the following journal article. Read it carefully
and produce a structured, detailed, and engaging bilingual summary.

──────────── Source Material ────────────

Journal:       {journal}
Volume/Issue:  Vol. {volume}, No. {issue}
Date:          {date}

Article title:
{article_title}

Authors:
{authors}

Cover description:
{cover_description}

──── Full Text (may be truncated) ────

{fulltext}

──────────── Output Instructions ────────────

Write a 4-part structured summary in BOTH Chinese and English. 
Do not be overly brief. Provide enough depth, context, and concrete details 
so the reader truly understands the mechanics and significance of the research, 
but avoid academic jargon and repetitive filler.

**Chinese summary format** (use these exact section headers):

【總結】詳細概述文章的核心發現、突破點及其重要性。讓讀者一眼看出這項研究的價值所在。

【研究問題】這篇文章探討的具體問題是什麼？過去的研究有什麼盲點或不足（研究缺口）？為什麼解決這個問題至關重要？

【研究方法】具體且清晰地解釋作者的研究步驟。他們使用了什麼獨特的數據、實驗設計、技術或理論框架？請用通俗易懂的方式拆解複雜的方法論。

【結果】列出具體的關鍵發現（必須包含重要的數據、比例或具體案例）。這些結果代表了什麼意義？對未來的領域發展或實際應用有什麼深遠影響？

**English summary format** (use these exact section headers with bold markdown):

**Summary:** A comprehensive overview of the article's core discovery, its breakthrough nature, and its overall significance. 

**Problem:** What specific question does the article address? What is the historical context or the gap in previous research? Why is this a crucial problem to solve?

**Approach:** Explain the methodology clearly and step-by-step. What unique data, experimental designs, technologies, or theoretical frameworks were utilized? Break down complex methods into understandable concepts.

**Results:** Detail the key findings, including specific and striking data points, percentages, or examples. What do these results mean, and what are their broader implications for the field or society?

Length constraint: Each section should be 1 to 2 well-developed paragraphs (roughly 80–150 words per section). Be specific, vivid, and intellectually engaging.

──────────── Output Format ────────────

Return a JSON object with EXACTLY this structure (no extra keys):

{{
  "title": {{
    "zh": "引人入勝的繁體中文標題",
    "en": "Compelling English Title"
  }},
  "summary": {{
    "zh": "【總結】...\\n\\n【研究問題】...\\n\\n【研究方法】...\\n\\n【結果】...",
    "en": "**Summary:** ...\\n\\n**Problem:** ...\\n\\n**Approach:** ...\\n\\n**Results:** ..."
  }}
}}
"""
