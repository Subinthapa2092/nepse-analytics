# nepse-analytics

Open-source NEPSE data pipeline and analytics platform — reliable price/floorsheet
scraping, broker flow analysis, and technical screening for the Nepal Stock Exchange.
Built in public, solo, from scratch.

## Status

🚧 Early build — daily price scraper in progress.

## Why

Existing NEPSE tools (Chukul, Nepalytix, Merolagani) are either paywalled,
closed-source, or unreliable. This is an attempt to build something
transparent and free, starting with a reliable data pipeline — with the
methodology documented as it's built, not hidden behind a black box.

## Roadmap

- [ ] Reliable single-symbol price scraper
- [ ] Scheduled daily ingestion (GitHub Actions)
- [ ] All-symbol price history in Postgres
- [ ] Floorsheet ingestion
- [ ] FastAPI backend
- [ ] React frontend with live candlestick charts
- [ ] Broker accumulation/distribution detection (clustering)
- [ ] Technical pattern screener (VCP / CANSLIM style)

## Project structure

```
nepse-analytics/
├── .github/workflows/   # scheduled scraping jobs (GitHub Actions cron)
├── scraper/              # fetching + parsing logic
├── database/              # DB models and connection handling
├── api/                    # FastAPI app (added in a later phase)
├── frontend/                # React app (added in a later phase, or separate repo)
├── notebooks/                # exploratory analysis, clustering work
├── tests/
└── docs/                      # notes on data sources, what breaks, why
```

## Setup

1. Clone the repo and create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate   # venv\Scripts\activate on Windows
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your own values:
   ```bash
   cp .env.example .env
   ```
4. Run the scraper:
   ```bash
   python scraper/fetch_prices.py
   ```

## Contributing

This is currently a solo learning project, built openly. Issues and
suggestions are welcome once the core pipeline is stable.

## License

MIT — see [LICENSE](LICENSE).
