# 🐾 NYC Lost & Found Pet Matcher

Automatically matches **lost** NYC pets with **found** ones, then:

- 📧 emails you a **weekly digest** of new high-confidence matches, and
- 🌐 publishes a **daily-refreshed public dashboard** of the uncertain
  *possible-match* band plus stats & trends.

It scrapes two public sources, normalizes them into one schema, and runs a
**two-stage matcher**: a cheap attribute filter screens out obvious misses, then
**Claude vision** confirms photos only on the survivors.

## Why these sources

[Animal Care Centers of NYC (ACC)](https://www.nycacc.org/services/lost-and-found/)
doesn't host its own searchable database — it funnels everyone into **Petco Love
Lost**, which aggregates ACC/shelter intakes plus Nextdoor and Ring Neighbors
posts. So this project uses:

- **Petco Love Lost** — the backbone (both lost & found). The "New York" feed is
  NY *state*, so records are filtered to NYC by ZIP/coordinates.
- **NYC Craigslist** lost & found (`/search/laf`) — community posts, filtered to
  the five boroughs.

PawBoost is intentionally excluded (it blocks automated access). Petco already
does on-demand facial matching; this project's distinct value is **cross-source
aggregation + standing automated matching**.

## How matching works

1. **Stage 1 — attributes** (`match/filter.py`): hard gates drop impossible pairs
   (different species, impossible dates, non-adjacent boroughs / >~10mi apart).
   Survivors get an additive similarity score from species, color, breed, size,
   sex, geography, date proximity, and free-text. Species alone (0.30) sits at the
   floor; corroborating signals push a pair up and rank it for the photo budget.
2. **Stage 2 — photos** (`match/photo.py`): the top-ranked survivors with photos
   on both sides go to **Claude vision**, which returns a same-animal likelihood.
   Every comparison is cached by photo-URL pair, so re-runs never re-pay.
3. **Tiers** (`match/pipeline.py`): `high` (→ email + dashboard), `possible`
   (→ dashboard only — the "worth a human look" band), `rejected` (hidden).
   Attribute-only matches (no photo) are capped and require a distinguishing
   attribute overlap, so the dashboard never floods with species-only pairs.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # fill in ANTHROPIC_API_KEY + email creds

# Smoke-test the scrapers (prints normalized records):
python -m petmatch.sources.petco --limit 3
python -m petmatch.sources.craigslist --limit 3

# Full pipeline, no email, attribute-only (no API cost):
python -m petmatch.main --limit 40 --no-photo --dry-run

# Real run with photo confirmation + dashboard (no email unless --send-email):
python -m petmatch.main

# Rebuild the dashboard from stored data and preview it locally:
python -m petmatch.dashboard
python scripts/serve_site.py   # then open http://localhost:8011

pytest -q
```

### Useful flags (`python -m petmatch.main`)

| flag | effect |
|---|---|
| `--limit N` | cap records per source (testing) |
| `--no-photo` | skip Claude vision (attribute-only) |
| `--send-email` | send the weekly digest (default: off) |
| `--dry-run` | never send; print the digest to console |
| `--skip-scrape` | reuse stored pets; just rematch + rebuild |
| `--sources petco,craigslist` | choose sources |

## Deploy (GitHub Actions + Pages)

1. Push this repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions.**
3. Add repo **secrets**: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `REPORT_EMAIL`,
   `REPORT_FROM` (a verified Resend sender; or use SMTP, see `.env.example`).
4. Add repo **variables**: `PETMATCH_DASHBOARD_URL` (your Pages URL),
   optionally `PETMATCH_VISION_MODEL` (`claude-opus-4-8` default, or
   `claude-haiku-4-5` to cut cost).
5. `.github/workflows/run.yml` runs **daily** (scrape + match + dashboard) and
   emails on **Mondays**. The SQLite DB (`data/petmatch.db`) is committed back
   each run so "already emailed" state persists. Trigger manually from the
   **Actions** tab (with *force_email* to test the email path).

## Notes on scraping & privacy

Built for **personal, non-commercial** use: low request rate, honest User-Agent,
on-disk caching, no republishing of contact info (the dashboard is link-back
only — viewers click through to the original post). Matches are *candidates*,
not confirmations — always verify via the source listing. Review each site's
Terms of Service before deploying.
```
