PYTHONPATH=src python3 scripts/init_db.py
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.discover_listings --max-pages 2
PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.scrape_listing_details --limit 10 --max-workers 1