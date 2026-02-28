# SciCover

**Bilingual cover-story summaries from leading science journals, refreshed every week.**

SciCover scrapes the current cover stories of major scientific journals (Nature,
Science, Cell, …), generates concise English **and** Chinese summaries with an
LLM, and publishes them to a static site on GitHub Pages — all fully automated
with GitHub Actions.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    GitHub Actions                         │
│                                                          │
│  ┌─────────────────────┐      ┌───────────────────────┐  │
│  │ scrape-and-summarize │      │       deploy          │  │
│  │   (Sat 06:00 UTC)   │      │  (on push to main)    │  │
│  │                      │      │                       │  │
│  │  1. Scrape journals  │─────▶│  1. npm ci && build   │  │
│  │  2. LLM summarise    │ push │  2. Copy data/images  │  │
│  │  3. Commit data/     │      │  3. Upload artifact   │  │
│  │     & images/        │      │  4. Deploy Pages      │  │
│  └─────────────────────┘      └───────────────────────┘  │
│                                          │               │
└──────────────────────────────────────────┼───────────────┘
                                           ▼
                                    GitHub Pages
                                  (static Vite app)

data/
├── nature.json          ← per-journal scraped data
├── science.json
└── …

images/
├── nature_cover.jpg     ← downloaded cover images
└── …

frontend/
├── src/                 ← Vite + vanilla-JS app
├── public/
│   └── favicon.svg
├── package.json
└── vite.config.js
```

---

## Quick Start (local development)

```bash
# 1. Clone
git clone https://github.com/<owner>/scicover.git
cd scicover

# 2. Install frontend dependencies
cd frontend
npm install

# 3. Symlink (or copy) data so the dev server can serve it
ln -s ../data   public/data
ln -s ../images public/images

# 4. Start the dev server
npm run dev
```

The site opens at **http://localhost:5173**.

### Running the scraper locally

```bash
pip install -r scripts/requirements.txt

# Scrape all journals
python -m scripts.main --journal all

# Scrape a single journal
python -m scripts.main --journal nature
```

Set `GITHUB_TOKEN` (a PAT with models scope) in your environment or a `.env`
file before running.

---

## GitHub Actions Pipelines

### 1. Scrape & Summarise (`scrape-and-summarize.yml`)

| Trigger | Cron every Saturday 06:00 UTC, or manual dispatch |
|---------|--------------------------------------------------|
| What    | Runs the Python pipeline, commits updated `data/` and `images/` |
| Secret  | `MODELS_PAT` — a GitHub PAT with access to the Models API |

### 2. Deploy (`deploy.yml`)

| Trigger | Push to `main` that touches `frontend/**`, `data/**`, or `images/**` |
|---------|----------------------------------------------------------------------|
| What    | Builds the Vite app, bundles data/images, deploys to GitHub Pages    |

The deploy job uses the official `actions/deploy-pages` action with
`id-token: write` for OIDC-based deployment.

---

## Data Schema

Each journal file in `data/` (e.g. `data/nature.json`) follows this schema:

```jsonc
{
  "journal":    "Nature",
  "url":        "https://www.nature.com/nature/current-issue",
  "scrapedAt":  "2025-06-07T06:02:14Z",
  "cover": {
    "image":    "images/nature_cover.jpg",
    "title":    "Cover story headline",
    "summary": {
      "en":     "One-paragraph English summary …",
      "zh":     "一段中文摘要 …"
    },
    "doi":      "10.1038/s41586-025-XXXXX",
    "link":     "https://www.nature.com/articles/…"
  }
}
```

---

## Adding a New Journal

1. Create a new scraper module in `scripts/scrapers/` (e.g.
   `scripts/scrapers/lancet.py`).
2. Implement the `scrape() -> dict` function returning the schema above.
3. Register the journal in `scripts/config.py` under the `JOURNALS` dict.
4. Run locally to verify: `python -m scripts.main --journal lancet`.
5. Open a PR — the weekly cron will pick it up automatically after merge.

---

## License

[MIT](LICENSE)
