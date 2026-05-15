# S&P 500 AI Business Exposure Visualizer

A research tool for visually exploring how AI may reshape business models across the S&P 500.  
This is not an investment recommendation engine. It is a development/research surface for structured comparison.

**Live demo (local): [http://127.0.0.1:8000/](http://127.0.0.1:8000/)**  
**Live demo (GitHub Pages): `https://songchch2005.github.io/sp500-ai-Visualizer/`**

---

## What's Here

The project builds an interactive treemap where:

- **Area** = company market cap
- **Color** = selected AI-business dimension
- **Grouping** = sector-level structure

Current dataset covers ~S&P 500 constituents (latest run: 492 business entities after share-class merging).

---

## LLM-Powered Coloring

Like Karpathy's `jobs` map, this repo includes a full promptable scoring pipeline:

- You define a rubric in `score.py`
- LLM scores each company
- Treemap recolors by selected layer

Current layers:

- `AI Composite Index`
- `AI Revenue Tailwind`
- `Pricing Power Risk`
- `Channel Control Risk`
- `AI Operating Leverage`
- `Data / Distribution Moat`
- `AI Infrastructure Exposure`

Scores are **0-10** and are **business-structure signals**, not return forecasts.

### Metric Meanings (What Each Score Is For)

- `AI Composite Index`  
  A blended summary score (0-10) of net AI business position. Higher means the company looks better positioned structurally across demand tailwind, operating leverage, moat, and infrastructure relevance, after accounting for pricing/channel risks.

- `AI Revenue Tailwind`  
  How directly AI can expand the company's revenue pool (new products, stronger usage, higher monetization).

- `Pricing Power Risk`  
  Risk that AI weakens the company's existing pricing power, take rate, or gross-margin structure.

- `Channel Control Risk`  
  Risk that AI intermediaries (assistants/agents/platforms) weaken the company's control of demand routing or customer interface.

- `AI Operating Leverage`  
  Potential for AI to improve internal productivity, throughput, and cost efficiency.

- `Data / Distribution Moat`  
  Strength of defensibility from proprietary data, workflow lock-in, distribution, regulation, or installed base.

- `AI Infrastructure Exposure`  
  Direct exposure to AI buildout (chips, cloud, networking, data centers, power, and enabling stack).

---

## What These Scores Are Not

- They do **not** predict stock returns.
- They do **not** model valuation, rates, positioning, macro, or timing.
- They do **not** replace deep fundamental work.
- They are LLM-assisted estimates and should be used as a screening/discovery layer.

---

## Data Pipeline

1. **Universe build** (`rebuild_sp500_universe.py`)  
   Rebuilds `companies.csv` using index constituent sources + metadata enrichment.

2. **10-K extraction** (`fetch_filings.py`)  
   Pulls latest 10-K metadata and extracts Business / Risk sections into:
   - `filings/<slug>.json`
   - `company_pages/<slug>.md`

3. **LLM scoring** (`score.py`)  
   Scores each company using a structured rubric and outputs `scores.json`.

4. **Site data build** (`build_site_data.py`)  
   Merges companies + scores + filing metadata into:
   - `site/data.json`
   - `site/data.js` (offline fallback for direct `index.html` opening)

5. **Prompt pack** (`make_prompt.py`)  
   Generates `prompt.md` for downstream LLM analysis.

6. **Frontend** (`site/index.html`)  
   Interactive static treemap + research panel + source filters.

---

## Key Files

| File | Purpose |
|---|---|
| `companies.csv` | Universe + basic metadata |
| `filings/` | Extracted filing payloads (`source`, `source_note`, business/risk text) |
| `company_pages/` | Company memos used for LLM scoring |
| `scores.json` | Multi-factor scores and confidence metadata |
| `site/data.json` | Frontend runtime data |
| `site/data.js` | Offline fallback data for `file://` mode |
| `prompt.md` | Consolidated promptable dataset |
| `site/index.html` | Interactive visualization |

---

## Setup

```bash
uv sync
```

Optional `.env`:

```bash
OPENROUTER_API_KEY=your_key
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.5-flash-lite
SEC_USER_AGENT=Your Name your@email.com
```

---

## Usage

### 1) Build / refresh data

```bash
uv run python rebuild_sp500_universe.py
uv run python fetch_filings.py --only-seed
uv run python score.py --provider gemini --sample-size 1
uv run python build_site_data.py
uv run python make_prompt.py
```

### 2) Run local demo

```bash
cd site
python -m http.server 8000
```

Open: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## Notes On Entity Handling

- `GOOG` + `GOOGL` are merged into one business entity (`GOOGL+GOOG`) for research consistency.
- Share-class info is preserved in `share_classes` for transparency.

---

## Deployment (GitHub Pages)

If you want a public live demo link like `jobs`:

1. Push `site/` to your repo
2. Enable GitHub Pages (branch root or `/docs`)
3. Set live URL in this README:
   - `https://songchch2005.github.io/sp500-ai-Visualizer/`

---

## Caveat

This map is best used as a **question generator**:

- Which sectors have high AI tailwind but low moat?
- Which businesses have high channel risk but strong current economics?
- Where is model disagreement high and worth deeper manual review?

Treat the outputs as a structured starting point, not final truth.
