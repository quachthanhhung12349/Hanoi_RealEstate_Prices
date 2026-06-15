# Project Structure

## Directories

- `src/hanoi_real_estate/`
  - `config.py`: central paths and runtime configuration.
  - `db.py`: SQLite connection and schema bootstrap.
  - `models.py`: lightweight typed records for scraper I/O.
  - `parsers.py`: parsing and normalization logic extracted from notebooks.
  - `scrapers/discover_listings.py`: search result crawler.
  - `scrapers/scrape_listing_details.py`: listing detail crawler.
  - `dashboard/`: Streamlit app modules.
- `sql/schema.sql`: initial SQLite schema for the MVP.
- `scripts/init_db.py`: initialize the local SQLite database.
- `data/`: SQLite file and derived exports.
- `logs/`: scraper and scheduler logs.
- `docs/`: implementation notes and architecture docs.

## Table Roles

- `listing`: crawl queue and source-of-truth for listing lifecycle.
- `listing_current`: latest scraped detail snapshot.
- `address`: nullable location details kept separate for future normalization.
- `listing_history`: cheap temporal history for price and status changes.
- `scrape_errors`: operational visibility and retry diagnostics.

## Next Build Steps

1. Move notebook parsing logic into `parsers.py`.
2. Port search-page crawl into `scrapers/discover_listings.py`.
3. Port detail crawl into `scrapers/scrape_listing_details.py`.
4. Add repository functions for upsert/query patterns.
5. Build Streamlit pages on top of `listing_dashboard_view`.
