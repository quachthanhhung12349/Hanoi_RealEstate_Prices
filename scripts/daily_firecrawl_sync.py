from __future__ import annotations

import argparse
import json
from pathlib import Path

from hanoi_real_estate.config import (
    DAILY_DISCOVER_URL,
    FIRECRAWL_DAILY_MAX_NEW,
    FIRECRAWL_DAILY_MAX_PAGES,
)
from hanoi_real_estate.firecrawl import (
    FirecrawlClient,
    FirecrawlScrapeResult,
    extract_candidate_listing_urls,
    parse_listing_detail_from_firecrawl,
)
from hanoi_real_estate.parsers import extract_listing_id, normalize_detail_payload
from hanoi_real_estate.repository import (
    fetch_existing_listing_ids,
    fetch_recent_scraped_listing_ids,
    mark_listing_failed,
    save_listing_detail,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Firecrawl-based incremental sync into PostgreSQL.")
    parser.add_argument("--discover-url", default=DAILY_DISCOVER_URL)
    parser.add_argument("--max-new", type=int, default=FIRECRAWL_DAILY_MAX_NEW)
    parser.add_argument("--max-pages", type=int, default=FIRECRAWL_DAILY_MAX_PAGES)
    parser.add_argument("--dry-run", action="store_true", help="Run discovery/detail parsing without writing to the database.")
    parser.add_argument(
        "--mock-dir",
        type=Path,
        default=None,
        help="Read Firecrawl responses from a local directory for testing. Expected files: page1.json, page2.json, listing_<id>.json",
    )
    return parser.parse_args()


def build_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    if "?cIds=" in base_url:
        prefix, suffix = base_url.split("?cIds=", 1)
        return f"{prefix}/p{page}?cIds={suffix}"
    return f"{base_url}/p{page}"


def load_mock_result(mock_dir: Path, key: str) -> FirecrawlScrapeResult:
    payload = json.loads((mock_dir / key).read_text(encoding="utf-8"))
    return FirecrawlScrapeResult(
        url=payload["url"],
        links=payload.get("links", []),
        markdown=payload.get("markdown"),
        raw_html=payload.get("rawHtml"),
        metadata=payload.get("metadata", {}),
    )


def scrape_with_source(client: FirecrawlClient | None, url: str, mock_dir: Path | None, key: str) -> FirecrawlScrapeResult:
    if mock_dir:
        return load_mock_result(mock_dir, key)
    if client is None:
        raise RuntimeError("Firecrawl client is not configured.")
    return client.scrape_page(url)


def collect_new_urls(
    client: FirecrawlClient | None,
    discover_url: str,
    max_pages: int,
    max_new: int,
    mock_dir: Path | None,
) -> list[str]:
    collected: list[str] = []
    recent_ids = fetch_recent_scraped_listing_ids(limit=500)

    for page in range(1, max_pages + 1):
        page_url = build_page_url(discover_url, page)
        key = f"page{page}.json"
        result = scrape_with_source(client, page_url, mock_dir, key)
        candidates = extract_candidate_listing_urls(result.links)
        candidate_ids = [extract_listing_id(url) for url in candidates]
        known_ids = fetch_existing_listing_ids(value for value in candidate_ids if value)

        for url, listing_id in zip(candidates, candidate_ids):
            if listing_id is None:
                continue
            if listing_id in known_ids or listing_id in recent_ids:
                continue
            if url not in collected:
                collected.append(url)
            if len(collected) >= max_new:
                return collected
    return collected


def process_url(
    client: FirecrawlClient | None,
    url: str,
    dry_run: bool,
    mock_dir: Path | None,
) -> tuple[bool, str]:
    listing_id = extract_listing_id(url)
    if listing_id is None:
        return False, f"Could not infer listing id from URL: {url}"

    try:
        result = scrape_with_source(client, url, mock_dir, f"listing_{listing_id}.json")
        raw = parse_listing_detail_from_firecrawl(result)
        payload = normalize_detail_payload(raw)
        if not dry_run:
            save_listing_detail(payload)
        return True, listing_id
    except Exception as exc:
        if not dry_run:
            mark_listing_failed(listing_id, type(exc).__name__, str(exc), stage="detail")
        return False, f"{listing_id}: {exc}"


def main() -> None:
    args = parse_args()
    client = None if args.mock_dir else FirecrawlClient()
    urls = collect_new_urls(
        client=client,
        discover_url=args.discover_url,
        max_pages=max(1, args.max_pages),
        max_new=max(1, args.max_new),
        mock_dir=args.mock_dir,
    )

    if not urls:
        print("No new URLs discovered.")
        return

    ok = 0
    fail = 0
    for url in urls:
        success, message = process_url(client, url, args.dry_run, args.mock_dir)
        if success:
            ok += 1
            print(f"OK {message}")
        else:
            fail += 1
            print(f"FAIL {message}")

    print(f"Discovered new URLs: {len(urls)}")
    print(f"Processed successfully: {ok}")
    print(f"Failed: {fail}")
    print(f"Dry run: {'yes' if args.dry_run else 'no'}")


if __name__ == "__main__":
    main()
