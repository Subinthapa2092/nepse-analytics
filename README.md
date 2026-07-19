# nepse-analytics

Open-source NEPSE data pipeline and analytics platform for reliable price and floorsheet scraping, broker flow analysis, and technical screening for the Nepal Stock Exchange.

Built in public, solo, from scratch.

## Status

🚧 Early build. Daily price scraper in progress.

## Why

Existing NEPSE tools such as Chukul, Nepalytix, and Merolagani are either paywalled, closed source, or unreliable.

This project aims to build a transparent and free alternative, starting with a reliable data pipeline. Every step of the methodology will be documented openly instead of hidden inside a black box.

## Roadmap

- [ ] Reliable single-symbol price scraper
- [ ] Scheduled daily ingestion using GitHub Actions
- [ ] All-symbol price history stored in PostgreSQL
- [ ] Floorsheet ingestion
- [ ] FastAPI backend
- [ ] React frontend with live candlestick charts
- [ ] Broker accumulation and distribution detection using clustering
- [ ] Technical pattern screener (VCP and CANSLIM style)

## Project Structure

```text
nepse-analytics/
├── .github/
│   └── workflows/          # Scheduled scraping jobs (GitHub Actions)
├── scraper/                # Fetching and parsing logic
├── database/               # Database models and connection handling
├── api/                    # FastAPI application
├── frontend/               # React application
├── notebooks/              # Exploratory analysis and clustering
├── tests/
├── docs/                   # Documentation and research notes
├── .env.example
├── requirements.txt
├── README.md
└── LICENSE
```

## Features

- Reliable NEPSE daily price scraping
- Historical price data collection
- Floorsheet data ingestion
- Broker-wise accumulation and distribution analysis
- Technical screening for stocks
- REST API built with FastAPI
- Interactive React dashboard
- Automated daily data updates using GitHub Actions
- Open-source and fully transparent development

## Tech Stack

- Python
- BeautifulSoup
- Requests
- Pandas
- PostgreSQL
- SQLAlchemy
- FastAPI
- React
- GitHub Actions
- Docker (planned)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/nepse-analytics.git
cd nepse-analytics
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it.

Linux/macOS

```bash
source venv/bin/activate
```

Windows

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example environment file.

```bash
cp .env.example .env
```

Fill in your PostgreSQL credentials and other configuration values.

### 5. Run the scraper

```bash
python scraper/fetch_prices.py
```

## Future Plans

- Real-time market monitoring
- Portfolio tracker
- Broker heatmaps
- Sector performance dashboard
- Financial statement analysis
- Dividend and bonus history
- Candlestick pattern detection
- Machine learning based price prediction
- AI-powered stock screener
- Public REST API
- Docker deployment
- Cloud hosting

## Contributing

This project is currently being developed as a solo learning project.

Once the core data pipeline becomes stable, contributions, issue reports, feature requests, and pull requests will be welcomed.

## License

This project is licensed under the MIT License.

See the `LICENSE` file for more information.