Phase 3 Operating Plan: Local Selenium + Daily Firecrawl

Architecture

    Storage Layer (Source of Truth): Supabase/PostgreSQL

    Local Backfill Path: Selenium-based local scraping on the developer machine for large historical imports, repair runs, and manual refreshes.

    Cloud Incremental Path: Firecrawl-based daily incremental sync for newest listings only.

    Dashboard Path: Streamlit reads from PostgreSQL/Supabase and does not perform scraping.

Execution Strategy

    Local Machine:
        Use `discover_listings.py` and `scrape_listing_details.py` for deep backfill and repair work.
        Migrate local SQLite data into PostgreSQL when needed.

    GitHub Actions:
        Use Actions only as a scheduler/orchestrator.
        Do not run Selenium or Chrome in Actions.
        Run `scripts/daily_firecrawl_sync.py` once a day with `DATABASE_URL` and `FIRECRAWL_API_KEY`.

Daily Firecrawl Sync Policy

    Canonical category URL: `https://batdongsan.com.vn/ban-dat-ha-noi?cIds=41`

    Daily flow:
        Scrape page 1 through Firecrawl.
        Extract listing URLs.
        Skip listing IDs already known in PostgreSQL.
        If fewer than 30 new URLs are found, scrape page 2.
        Stop after collecting at most 30 new URLs.
        Scrape detail pages through Firecrawl.
        Normalize through the existing payload path and save into PostgreSQL.

    Guardrails:
        Do not mark unseen listings inactive from the daily 1-2 page scan.
        Keep retries conservative for Firecrawl failures and rate limits.

Deployment Notes

    Required secrets:
        `DATABASE_URL`
        `FIRECRAWL_API_KEY`

    Optional settings:
        `FIRECRAWL_DAILY_MAX_NEW`
        `FIRECRAWL_DAILY_MAX_PAGES`
        `DAILY_DISCOVER_URL`

Cost/Operational Intent

    Selenium stays local to reduce ban/block risk in hosted CI.

    Firecrawl handles only the newest small daily increment so the free tier remains viable.

    The daily sync is intentionally incomplete if listing churn is higher than the daily cap; local Selenium remains the recovery path.
