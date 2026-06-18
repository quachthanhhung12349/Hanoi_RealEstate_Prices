# Hanoi Real Estate Prices Analysis and Recommendation System

This repository is currently **Phase 2** of the project.

## Project Overview

This project is a Hanoi real estate data platform built in stages.

At a high level, it aims to:

1. scrape and store Hanoi real estate listing data
2. clean and analyze pricing and location information
3. visualize price patterns geographically
4. build features that can later support price prediction and recommendations

The current system combines:

- resumable web scraping from `batdongsan.com.vn`
- SQLite-based data storage
- exploratory analytics and notebook workflows
- a Streamlit dashboard for both tabular analysis and GIS-based map views

## Phase 2

Phase 2 is focused on **GIS integration and spatial price analysis**.

This phase builds on the Phase 1 scraping/data foundation and adds map-based workflows so the project can reason about price patterns geographically, not just by rows in a table.

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
  - Hanoi boundary validation
  - GIS preview layers
  - interpolated price surface view
  - average price hex-bin view
  - district average price view
- GIS helpers for:
  - loading Hanoi boundary GeoJSON
  - loading district polygons
  - boundary and district validation
  - interpolated spatial price surfaces
  - district-level average price aggregation
  - shortest-path preparation with OSMnx

## What Phase 2 Is About

Phase 2 is the **spatial analysis and map intelligence** stage.

The goal here is to turn listing coordinates into usable GIS features that help:

- identify suspicious or misplaced coordinates
- understand price structure by area
- compare regions visually
- prepare spatial features for later machine learning work

## Current Project Structure

- `src/hanoi_real_estate/scrapers/`: live scraping code
- `src/hanoi_real_estate/repository.py`: SQLite repository layer
- `src/hanoi_real_estate/analytics.py`: analysis and feature engineering
- `src/hanoi_real_estate/gis.py`: GIS helpers for boundaries, district joins, map layers, and routing
- `src/hanoi_real_estate/dashboard/app.py`: Streamlit dashboard
- `scripts/`: utility scripts for DB init, imports, and GIS cache building
- `notebooks/`: exploratory notebooks including the GIS GeoJSON quickstart
- `data/`: SQLite database and cached GIS assets

## Current Behavior

### Discovery

The discovery scraper can stop early when it reaches a page that contains only listings already seen in the most recent scraped set. This is intended to avoid crawling deep into old pages unnecessarily during incremental updates.

### Detail scraping

Detail scraping is resumable by design:

- pending work is stored in SQLite
- successfully scraped listings move to `done`
- failed listings move to `failed`
- stopping the process does not lose progress
- restarting the scraper continues from the remaining pending queue

### GIS dashboard behavior

The GIS dashboard currently supports:

- Hanoi boundary overlay for coordinate QA
- district-level polygon matching when district polygons are available
- point-based inspection of listings
- interpolated price surface view for sparse-area approximation
- average price hex-bin view
- district-average coloring mode

The GIS visualization uses clipped `Giá/m²` values in the map layers so extreme outliers do not dominate the color scale.

## Environment and Dependencies

To make the project easier to move and deploy on another machine, the Python dependencies are now split into:

- `requirements.txt`: core dependencies for scraping, importing, SQLite workflows, the Streamlit dashboard, and GIS features
- `requirements-notebooks.txt`: optional extras for notebooks and exploratory analysis

Recommended baseline:

- Python `3.10+`
- `pip`
- Google Chrome or Chromium installed locally for Selenium scraping

Create an isolated environment and install the core dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

If you also want to run the notebooks:

```bash
python3 -m pip install -r requirements-notebooks.txt
```

Core Python libraries used by the project:

- `pandas`
- `plotly`
- `selenium`
- `streamlit`
- `tqdm`
- `undetected-chromedriver`
- `geopandas`
- `osmnx`
- `pydeck`
- `pyogrio`
- `shapely`

Optional notebook libraries:

- `jupyter`
- `matplotlib`
- `numpy`
- `seaborn`
- `ipykernel`

## System Dependency for Scraping

The live scrapers use Selenium with `undetected-chromedriver`, so the machine also needs a local Chrome/Chromium browser installation.

The current code looks for Chrome in these default locations:

- Linux: `/opt/google/chrome/google-chrome`
- macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`

If Chrome is installed somewhere else, update `CHROME_BINARY` in `src/hanoi_real_estate/config.py`.

## Local and Demo Databases

The project currently uses SQLite locally while Phase 3 PostgreSQL/Supabase support is being prepared.

Database path behavior:

- `data/bds_live.sqlite3`: local runtime database used by scraping/import workflows
- `data/demo.sqlite3`: temporary bundled demo database for public/demo dashboard use
- `HANOI_RE_DB_PATH`: optional environment variable to force a specific SQLite database path

By default, the app uses `data/bds_live.sqlite3` if it exists. If it does not exist, it falls back to `data/demo.sqlite3`.

The live runtime database is ignored by git so scraper runs do not constantly dirty the working tree. The demo database is intentionally kept as a temporary public sample until the project fully transitions to hosted PostgreSQL.

## Useful Commands

Initialize the database:

```bash
PYTHONPATH=src python3 scripts/init_db.py
```

Discover listing URLs:

```bash
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.discover_listings --max-pages 200
```

Scrape listing details in resumable batches:

```bash
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.scrape_listing_details --limit 0 --max-workers 1 --batch-limit 5
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

Build and cache Hanoi district polygons for district-level GIS validation:

```bash
PYTHONPATH=src python3 scripts/build_hanoi_district_cache.py
```

Open the GIS/GeoJSON quickstart notebook:

```bash
jupyter notebook notebooks/gis_geojson_quickstart.ipynb
```

## Planned Next Phases

### Phase 3

Deploy the project and implement background scraping for constantly up-to-date data.

### Phase 4

An ML model to help predict house prices in Hanoi.

### Phase 5

RAG/LLM integration with both the scraped data and ML model outputs to:

- identify pros and cons of each region
- suggest suitable house-buying options for:
  - individuals
  - families
  - investors
