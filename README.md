# Hanoi Real Estate Prices Analysis and Recommendation System

This repository is currently **Phase 1** of the project.

## Phase 1

Phase 1 is focused on:

- scraping Hanoi real estate listing URLs and listing details from `batdongsan.com.vn`
- storing the scraped data in SQLite
- importing existing CSV and href snapshots into the database
- building the first dashboard for basic exploratory analysis

At this stage, the system supports:

- `discover_listings.py` to discover listing URLs
- `scrape_listing_details.py` to scrape listing details with resume behavior through database state
- import scripts for:
  - `hrefs.txt` / `hrefs_old.txt`
  - `data_bds.csv`
- `analytics.py` for notebook-aligned cleaning and derived metrics
- a Streamlit dashboard for:
  - table view
  - distance to Hanoi center vs price per m²
  - regional house price statistics

## What Phase 1 is about

Phase 1 is the **data scraping and initial data analysis** stage.

The goal here is to create a working end-to-end MVP that can:

1. collect listing data
2. store it in a structured database
3. support basic inspection and analysis through a dashboard

## Current Project Structure

- `src/hanoi_real_estate/scrapers/`: live scraping code
- `src/hanoi_real_estate/repository.py`: SQLite repository layer
- `src/hanoi_real_estate/analytics.py`: analysis and feature engineering
- `src/hanoi_real_estate/dashboard/app.py`: Streamlit dashboard
- `scripts/`: utility scripts for DB init and legacy data import
- `data/`: SQLite database

## MVP Behavior

### Discovery

The discovery scraper can stop early when it reaches a page that contains only listings already seen in the most recent scraped set. This is intended to avoid crawling deep into old pages unnecessarily during incremental updates.

### Detail scraping

Detail scraping is resumable by design:

- pending work is stored in SQLite
- successfully scraped listings move to `done`
- failed listings move to `failed`
- stopping the process does not lose progress
- restarting the scraper continues from the remaining pending queue

## Useful Commands

Initialize the database:

```bash
PYTHONPATH=src python3 scripts/init_db.py
```

Discover listing URLs:

```bash
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.discover_listings --max-pages 2
```

Scrape listing details in resumable batches:

```bash
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.scrape_listing_details --limit 10 --max-workers 1 --batch-limit 1
```

Import legacy href data:

```bash
PYTHONPATH=src python3 scripts/import_href_file.py hrefs_old.txt
```

Import legacy CSV data:

```bash
PYTHONPATH=src python3 scripts/import_csv_to_db.py
```

Run the dashboard:

```bash
./scripts/run_dashboard.sh
```

## Planned Next Phases

### Phase 1b

Deploy the project and implement background scraping for constantly up-to-date data.

### Phase 2

GIS integration to provide better house price representation via an interactive heatmap.

### Phase 3

An ML model to help predict house prices in Hanoi.

### Phase 4

RAG/LLM integration with both the scraped data and ML model outputs to:

- identify pros and cons of each region
- suggest suitable house-buying options for:
  - individuals
  - families
  - investors
