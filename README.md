# SciCover Summary
### A web-based application that provide Bilingual Summaries of cover articles from scientific journals

Other Language：[Chinese](README.CN.md)

![cover](images/cover.png)
---

## Why SciCover?
Every week, top-tier journals like *Science*, *Nature*, and *Cell* publish groundbreaking cover research. However, these insights are often inaccessible to general readers due to several barriers:

* **Language Barrier:** Papers are written entirely in English with dense technical jargon, making them difficult for non-native speakers to digest.
* **Information Fragmentation:** Tracking multiple journals requires constant switching between various official websites.
* **Inaccessible Content:** Even with a high level of English proficiency, the academic writing style can be intimidating for the general public.
* **Time Consumption:** Manually checking journal websites every week to identify cover stories is labor-intensive and inefficient.
* **Lack of Quality Science Communication:** There is a scarcity of real-time, high-quality Chinese interpretations of global scientific cover stories.

**SciCover** solves these problems. It curates cover stories from premier journals and uses AI to generate bilingual (Chinese-English) summaries, allowing anyone to easily grasp the latest scientific frontiers on a single platform.

---

## Key Features
### 🔬 Automated Journal Tracking
Automatically tracks the latest cover stories from *Science*, *Nature*, and *Cell*, eliminating the need for manual checks.

### 🌐 Bilingual AI Summaries
AI-generated summaries are not mere word-for-word translations, but "interpretative rewrites" designed for a general audience—ensuring clarity for Chinese readers while providing high-quality English insights.

### 📱 Modern Reading Experience
Designed with a magazine-style aesthetic inspired by *Quanta Magazine*, featuring:
* **Journal Filtering:** One-click toggling between *Science* / *Nature* / *Cell* or viewing all journals.
* **Dark Mode:** Comfortable reading for both day and night.
* **Responsive Layout:** Perfect presentation across mobile, tablet, and desktop.
* **Visual Gallery:** Display of cover art and in-text figures with bilingual captions.

### 📅 Historical Archive
Browse past cover stories by year and month to build your personal scientific reading timeline.

### 💰 Zero-Cost Operation
The entire site is deployed on **GitHub Pages** and utilizes the **GitHub Models API** free tier for summary generation, requiring no server costs or paid services.

---

## Online Preview
Deployed URL format: [SciCover Summary](https://lch99310.github.io/SciCover_Summary/)

---

## Adding New Journals
1.  Create a new scraper module in `scripts/scraper/` (e.g., `lancet_scraper.py`).
2.  Inherit from `BaseScraper` and implement the `scrape()` method.
3.  Register it in the `SCRAPER_MAP` within `pipeline/runner.py`.
4.  Add the journal to the `JOURNALS` array in `frontend/src/lib/constants.ts`.
5.  **Local Testing:** Run `python -m main --journal Lancet`.
6.  Once the PR is merged, the weekly schedule will automatically handle processing.

---

**License:** CC BY-NC-ND 4.0

