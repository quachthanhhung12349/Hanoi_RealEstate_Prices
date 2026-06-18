# Hanoi Real Estate Prices Analysis and Recommendation System

Live website: https://hanoirealestateprices-bnsxy55lsaau8jmmrzvay4.streamlit.app/

This repository is currently **Phase 3** of the project.

## Phase 3

Phase 3 is focused on:

- deploying the dashboard as a read-only Streamlit app backed by Supabase/PostgreSQL
- keeping scraping independent from the GUI so data collection can run on its own schedule
- running a daily Firecrawl incremental sync into Supabase
- supporting manual and large backfill scraping locally with Selenium-based scripts
- precomputing and caching GIS layers in PostgreSQL so the hosted app does not rebuild heavy map layers on every page load

At this stage, the system supports:

- `discover_listings.py` to discover listing URLs for deeper local scraping and repair runs
- `scrape_listing_details.py` to scrape listing details with resume behavior through database state
- `daily_firecrawl_sync.py` to perform daily incremental Firecrawl ingestion into PostgreSQL/Supabase
- GIS cache refresh inside the daily sync so hosted map layers stay up to date
- import scripts for:
  - `hrefs.txt` / `hrefs_old.txt`
  - `data_bds.csv`
- `analytics.py` for notebook-aligned cleaning and derived metrics
- a Streamlit dashboard for:
  - table view
  - distance to Hanoi center vs price per m2
  - regional house price statistics
  - GIS views backed by precomputed PostgreSQL cache tables

## What Phase 3 is about

Phase 3 is the **deployment and production data pipeline** stage.

The goal here is to create a working end-to-end system that can:

1. collect listing data through both local scraping and daily cloud sync
2. store the source-of-truth dataset in Supabase/PostgreSQL
3. refresh cached GIS outputs outside the web app
4. serve a fast, read-only dashboard through Streamlit Community Cloud

## Current Project Structure

- `src/hanoi_real_estate/scrapers/`: live scraping code for URL discovery and detailed scraping
- `src/hanoi_real_estate/firecrawl.py`: Firecrawl client and parsing helpers
- `src/hanoi_real_estate/repository.py`: PostgreSQL/SQLite repository layer plus GIS cache persistence
- `src/hanoi_real_estate/analytics.py`: analysis and feature engineering
- `src/hanoi_real_estate/gis.py`: GIS builders and cached GIS refresh/load helpers
- `src/hanoi_real_estate/dashboard/app.py`: Streamlit dashboard
- `streamlit_app.py`: Streamlit Community Cloud entrypoint
- `scripts/`: DB init, import utilities, and daily Firecrawl sync
- `sql/`: PostgreSQL schema and GIS cache tables
- `data/`: local SQLite database and local artifacts when working outside Supabase

## MVP Behavior

### Discovery

The discovery scraper can stop early when it reaches a page that contains only listings already seen in the most recent scraped set. This is intended to avoid crawling deep into old pages unnecessarily during incremental updates.

### Detail scraping

Detail scraping is resumable by design:

- pending work is stored in database state
- successfully scraped listings move to `done`
- failed listings move to `failed`
- stopping the process does not lose progress
- restarting the scraper continues from the remaining pending queue

### Daily sync and hosted GIS behavior

The hosted Streamlit app does not scrape data and does not recompute the heavy interpolation layer live.

- Firecrawl handles the daily incremental sync into Supabase/PostgreSQL
- manual scraping can still be run independently whenever needed
- the daily sync refreshes cached GIS tables after ingestion
- the Streamlit app reads listings and cached GIS layers from PostgreSQL/Supabase

## Technologies Used

- Scraping and parsing:
  - Selenium
  - undetected-chromedriver
  - Firecrawl
  - Requests
  - BeautifulSoup
- Data storage and access:
  - Supabase
  - PostgreSQL
  - SQLite
  - SQLAlchemy
  - Psycopg
- Dashboard and visualization:
  - Streamlit
  - Plotly
  - Pydeck
- GIS and geospatial processing:
  - GeoPandas
  - Shapely
  - Pyogrio
  - OSMnx

## Useful Commands

Initialize the local database:

```bash
PYTHONPATH=src python3 scripts/init_db.py
```

Discover listing URLs:

```bash
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.discover_listings --max-pages 200
```

Scrape listing details in resumable batches:

```bash
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.scrape_listing_details --limit 50 --max-workers 3 --batch-limit 40
```

Import legacy href data:

```bash
PYTHONPATH=src python3 scripts/import_href_file.py hrefs_old.txt
```

Import legacy CSV data:

```bash
PYTHONPATH=src python3 scripts/import_csv_to_db.py
```

Run the dashboard locally:

```bash
./scripts/run_dashboard.sh
```

Run the Streamlit Community Cloud entrypoint locally:

```bash
PYTHONPATH=src streamlit run streamlit_app.py
```

Run the daily Firecrawl sync plus GIS refresh:

```bash
PYTHONPATH=src python3 scripts/daily_firecrawl_sync.py
```

## Deployment Notes

For Streamlit Community Cloud:

- main file: `streamlit_app.py`
- Python version: `3.12`
- use `requirements.txt` for the hosted dashboard dependency set
- configure `DATABASE_URL` in Streamlit app secrets
- keep scraping and manual sync outside Streamlit

For the worker or scheduled sync environment:

- use `requirements-worker.txt`
- configure:
  - `DATABASE_URL`
  - `FIRECRAWL_API_KEY`
- run `scripts/daily_firecrawl_sync.py` once a day
- the daily sync refreshes cached GIS layers in PostgreSQL after ingestion

## Planned Next Phases

### Phase 4

An ML model to help predict house prices in Hanoi.

### Phase 5

RAG/LLM integration with both the scraped data and ML model outputs to:

- identify pros and cons of each region
- suggest suitable house-buying options for:
  - individuals
  - families
  - investors
