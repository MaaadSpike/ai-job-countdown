# AI Job Countdown

**English** | [中文](README.zh-CN.md)

Type in an occupation and see when AI agents could independently handle half of its work time, if AI capability keeps growing at its measured rate.

The method breaks each occupation into its O\*NET tasks, estimates how long a skilled person needs for one instance of each task, and applies the growth curve of AI agents' *time horizon* measured by [METR](https://metr.org).

> Research in progress. The countdown is a projection under stated assumptions, not a prediction. Being able to do a task is not the same as replacing the people who do it.

Full design: [docs/DESIGN.md](docs/DESIGN.md) ([中文](docs/DESIGN.zh-CN.md)).

## How it works

```
O*NET 30.2 task list ─┬─► estimate/  (Qwen2.5-32B on vLLM) ─► hours per instance + task type
                      │                                              │
                      │       annotate/ (human labels) ──► validates ┘
                      │                                              │
O*NET task ratings ───┴─► web/own_shares.py ─► share of work time ◄──┘
                                                     │
METR time-horizon trend (forecast/) ─────────────────┤
                                                     ▼
                              web/build_data.py ─► web/occupations.json ─► web/index.html
```

For each task, the waiting time until AI can do it is

```
months = doubling_time × log2(task_hours × difficulty_factor ÷ current_horizon)
```

The tasks are sorted by that waiting time, and their shares of work time are added up. The date at which the total reaches the chosen threshold (50% by default) is "AI capable". Adding an adoption lag gives "in practice".

## Data strategy

| Quantity | Source | Notes |
|---|---|---|
| Tasks and occupations | [O\*NET 30.2](https://www.onetcenter.org) (CC BY 4.0) | 876 occupations, 17,525 tasks. Phase 1 uses the same task subset as Hatgis-Kessell et al. (2026). |
| Hours for one instance of each task | **Our estimates**: Qwen2.5-32B-Instruct-AWQ on vLLM (`estimate/`) | End to end, by a skilled worker, without AI. Median of 5 samples. |
| Task type | Same model run | Computer-based, trust-based (needs in-person communication), or on-site. |
| Share of work time | **Our formula** (`web/own_shares.py`) | O\*NET frequency × O\*NET relevance × min(hours, 7), normalized within each occupation |
| AI capability | METR Time Horizon 1.1 | About 3.1 hours at 80% reliability and 16 hours at 50%. Doubling time 2.9–6.5 months depending on the fitting period. |
| Validation | Human labels (`annotate/`) | 8 duration bins and 3 task types, on a stratified sample of 300 tasks |

**Why we estimate durations ourselves.** No public dataset gives end-to-end durations for all O\*NET tasks. The closest one, Hatgis-Kessell et al. (2026), estimates a per-instance time *w* that is capped at 7 hours. That cap is fine for time shares but too short for comparing against AI time horizons. Their release is used here only as a comparison and is not part of the website data.

**Why the time-share formula caps hours at one workday.** O\*NET asks how *often* workers perform a task, for example "daily", not how often they *finish* one. A 300-hour research project that is worked on daily would otherwise count as 300 hours per day. The cap avoids that, at the cost of underweighting long tasks (see Limitations).

## Results so far

**Duration estimates.** 17,525 tasks on one A100 40GB took 3.96 hours at 1,261 output tokens/s, about $0.45 per 1,000 tasks at $1.99/hour.

Agreement with 51 human-labeled tasks (single annotator, 8 duration bins):

| Prompt | Within 1 bin | Quadratic weighted κ | Spearman | Bias on long tasks (≥4 h) | Type agreement |
|---|---|---|---|---|---|
| v2 | 75% | 0.58 | 0.69 | +0.22 bins | 84% |
| v3 | 94% | 0.70 | 0.64 | −0.50 bins | 86% |
| **v3.1 (used)** | 86% | 0.70 | 0.72 | 0.00 bins | 86% |

These 51 tasks were used to tune the prompt, so they are a development set. The final accuracy will be reported on a separate held-out set.

- v2 inflated short tasks. v3 fixed that but halved long tasks, which would have made countdowns look earlier. v3.1 restricts the "don't inflate" rule to quick routine actions.
- Hatgis-Kessell et al.'s *w* is within one bin of the same human labels only 51% of the time and is 1.45 bins too short on average. For the 214 tasks sitting at their 7-hour cap, our median estimate is 38 hours, and 86% are above 7 hours.
- Switching between our time shares and Hatgis-Kessell et al.'s changes the countdown by less than half a year for 85% of occupations (Spearman 0.87 across occupations).

## Website

A static site: one HTML file and two JSON data files (`web/occupations.json`, about 2 MB, and `web/news.json`). No backend; all calculations run in the browser.

- **Search** in Chinese or English, with Chinese names for all 876 occupations and extra aliases for about 120 common ones.
- **Seven-segment countdown** to the "in practice" date, with "AI capable" and "in practice" dates, plus the range across METR's doubling-time fits.
- **Assumption controls**: reliability (50% or 80%), doubling time, real-world difficulty factor, adoption lag, extra lag for trust-based tasks, and the threshold (half or three quarters of work time).
- **Task timeline**: each task's capability date and adoption lag. On-site tasks are marked as not covered by the trend.
- **Field news**: AI news for the occupation's field (one of 22 SOC major groups), each item marked "AI progress" or "reality check". Hand-picked items for a few occupations sit on top; the rest is collected daily by `news/collect.py` (see below). Below that, a search box looks up recent Google News coverage for the occupation (default keywords: occupation + AI, editable; two queries roughly label headlines as "AI progress" or "reality check") through a small Cloudflare Pages Function, `functions/api/search.js`; no API key needed, results cached for 6 hours.
- **Sharing**: a share image drawn in the browser (portrait 4:5 or square 1:1, Chinese or English) with a QR code back to the same occupation and assumptions; LinkedIn, X, the phone's share sheet, copy link and copy text. Links carry the assumptions (`?lang=en&d=2.9&k=8#15-1252.00`), so a shared link shows the same numbers.
- **Bilingual**: Chinese and English. The language follows `?lang=zh|en`, then the last choice, then the browser language.

## Repository layout

| Directory | Contents |
|---|---|
| `annotate/` | Streamlit labeling tool, guidelines, agreement metrics |
| `estimate/` | vLLM batch inference, prompt, evaluation against labels |
| `forecast/` | METR trend fitting, backtests, countdown algorithm |
| `web/` | Website, data build script, time-share formula, `news.json`, QR library (`vendor/`) |
| `news/` | Field definitions and search terms, hand-picked news, daily news collector |
| `functions/` | Cloudflare Pages Function for the live news search (`/api/search`) |
| `tests/` | pytest suite |
| `docs/` | Design doc (English and Chinese) |
| `data/`, `runs/` | Third-party data and model outputs; not committed |

## Running it

```bash
# 1. Data (data/ and runs/ are not in the repo; create them):
#    data/Task Ratings.xlsx               <- O*NET 30.2: https://www.onetcenter.org/dl_files/database/db_30_2_excel.zip
#    data/task_time_share_estimates.xlsx  <- https://github.com/Stephanehk/Estimating-Time-Spent-On-Work
#                                            (task list for step 2, and the optional comparison)

# 2. Estimate task durations (needs a GPU; ~4 hours on one A100 40GB)
cd estimate
bash setup.sh
python prepare_tasks.py --xlsx ../data/task_time_share_estimates.xlsx --out tasks.jsonl
python estimate.py --tasks tasks.jsonl --out ../runs/full-v3.1 --max-tokens 600

# 3. Build the website data and preview
cd ../web
python build_data.py                     # our time shares (default)
python build_data.py --shares stanford   # comparison: Hatgis-Kessell et al.'s time shares
python -m http.server 8000               # open http://localhost:8000 (no live news search)
# or, from the repo root, with the news search endpoint:  npx wrangler pages dev web

# 4. News (optional; a GitHub Action runs this daily)
cd ..
python news/collect.py -v                # Google News RSS per field → web/news.json
# With NEWS_LLM_API_KEY set (any OpenAI-compatible API; NEWS_LLM_BASE_URL / NEWS_LLM_MODEL),
# an LLM filters, classifies and translates the headlines; without it, keyword rules keep English headlines.
```

**Labeling.** See [`annotate/README.md`](annotate/README.md) and [`annotate/GUIDELINES.md`](annotate/GUIDELINES.md). Each annotator runs `streamlit run label_app.py` on their own computer and sends their `labels_<name>.csv` directly. Labels are not committed, so annotators stay independent.

## Tests and CI/CD

```bash
pip install -r requirements-dev.txt
pytest -q
```

The tests cover prompt parsing, an end-to-end run with a mock backend (including resuming), the countdown algorithm, the time-share formula, the news collector (RSS parsing, filtering, merging; offline), and the website data schemas.

- `.github/workflows/ci.yml` runs lint and tests on every push and pull request.
- `.github/workflows/deploy.yml` deploys `web/` to Cloudflare Pages. For now it only runs when triggered by hand.
- `.github/workflows/news.yml` collects news every day and commits `web/news.json` when it changes. Set the repository secret `NEWS_LLM_API_KEY` for Chinese translations; set the variable `NEWS_AUTO_DEPLOY=true` after launch to redeploy when news changes.

## Limitations

- **Long tasks are underweighted in time shares**, because each occurrence counts at most one workday. For occupations heavy in long work, such as software and research, the countdown may run about a year early.
- **METR's tasks are mostly software engineering.** The real-world difficulty factor is not calibrated yet; calibrating it is the main research question for the next phase.
- **Short tasks (under an hour) are overestimated** by about one bin. They are already within AI's current range, so the countdown is barely affected.
- **Task types are imperfect**, especially for supervising and evaluating staff, and for in-person care tasks that are labeled trust-based.
- **Human validation** so far uses one annotator. A second annotator and a held-out set are in progress.

## Data sources

- O\*NET 30.2 Database, U.S. Department of Labor, Employment and Training Administration (CC BY 4.0)
- METR, *Time Horizon 1.1*
- Comparison only: Hatgis-Kessell, Aguirre, Wan & Bommasani (2026), *Estimating Time Spent on Work Tasks*, arXiv:2608.05172
