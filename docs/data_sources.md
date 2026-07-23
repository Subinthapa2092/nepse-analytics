# Data source notes

Tracking what works, what breaks, and why — for future-me and anyone else
building on top of this.

## nepalstock.com (official NEPSE site)
- Uses an obfuscated/rotating auth token for API access.
- Unofficial Python libraries (`nepse_scraper`, `NepseUnofficialApi`) wrap
  this token logic, but break whenever NEPSE changes it.
- Decision: not using this directly for now — too fragile to depend on
  solo, without a team to maintain the reverse-engineering.

## merolagani.com
- ASP.NET WebForms site. Some pages (e.g. `LatestMarket.aspx`) may render
  as plain HTML tables. Others (e.g. price history on `CompanyDetail.aspx`)
  use `__doPostBack` / view state for pagination, which plain `requests`
  calls can't trigger without replicating the postback payload.
- Plan: start with the simplest static pages first, tackle postback-driven
  pages later (may need `requests` with manually captured `__VIEWSTATE`
  and `__EVENTVALIDATION` fields, or a headless browser like Playwright).

## sharesansar.com
- Not yet investigated. Candidate alternative if Merolagani proves too
  difficult to scrape reliably.

## Update this file whenever a source's structure changes or breaks.

## merolagani.com — price history (backfill)

- Price History tab requires Playwright (real headless browser), not
  requests+BS4, due to __doPostBack pagination behavior.
- Selectors in scraper/historical/fetch_history.py are PLACEHOLDERS as of
  first write — must be replaced with real ones found via browser DevTools
  before running (same process as the Day 1 live-price parser fix).
- Run manually via `python -m scraper.historical.backfill`, not on the
  daily cron — slow and deliberately rate-limited.
- Start with SYMBOLS_TO_BACKFILL as a short test list before running
  against all tracked symbols.
