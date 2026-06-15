from __future__ import annotations

import argparse
import time

from selenium.webdriver.common.by import By

from ..config import DEFAULT_DISCOVER_URL, DEFAULT_SEARCH_CATEGORY, HREFS_PATH
from ..parsers import extract_listing_id, infer_listing_type_from_url
from ..repository import (
    fetch_recent_scraped_listing_ids,
    mark_missing_listings_inactive,
    upsert_many_discovered_listings,
)
from .common import create_driver, sleep_jitter, wait_for_listing_cards


def get_hrefs_from_page(driver, url: str) -> list[str]:
    driver.get(url)
    wait_for_listing_cards(driver, timeout=90)
    elements = driver.find_elements(By.CLASS_NAME, "js__product-link-for-product-id")
    hrefs = [element.get_attribute("href") for element in elements]
    return [href for href in hrefs if href and "batdongsan.com.vn" in href]


def build_page_url(page: int, base_url: str) -> str:
    if page == 1:
        return base_url
    return f"https://batdongsan.com.vn/ban-dat-ha-noi/p{page}?cIds=41"


def discover_all(
    base_url: str = DEFAULT_DISCOVER_URL,
    max_pages: int | None = None,
    headless: bool = False,
    stop_when_reaching_recent: bool = True,
    recent_window: int = 100,
) -> list[str]:
    driver = create_driver(headless=headless)
    all_hrefs: list[str] = []
    recent_listing_ids = fetch_recent_scraped_listing_ids(limit=recent_window) if stop_when_reaching_recent else set()
    page = 1
    try:
        while True:
            if max_pages is not None and page > max_pages:
                break

            url = build_page_url(page, base_url)
            print(f"Discovering page {page}: {url}")
            hrefs = get_hrefs_from_page(driver, url)
            page_listing_ids = [extract_listing_id(href) for href in hrefs]
            page_listing_ids = [listing_id for listing_id in page_listing_ids if listing_id]
            before = len(all_hrefs)
            all_hrefs.extend(hrefs)
            all_hrefs = list(dict.fromkeys(all_hrefs))
            print(f"Collected {len(all_hrefs) - before} new urls on page {page}")

            if recent_listing_ids and page_listing_ids:
                overlap_count = sum(1 for listing_id in page_listing_ids if listing_id in recent_listing_ids)
                if overlap_count > 0:
                    print(
                        "Stopping discovery early because this page has reached already scraped listings."
                    )
                    break

            next_page = driver.find_elements(
                By.CSS_SELECTOR,
                "a.re__pagination-icon:not(.re__pagination-icon--no-effect)",
            )
            if not next_page:
                break

            page += 1
            sleep_jitter(2.0, 4.0)
    finally:
        driver.quit()

    return all_hrefs


def persist_discovered_urls(urls: list[str], search_category: str = DEFAULT_SEARCH_CATEGORY) -> int:
    records = []
    seen_listing_ids: list[str] = []
    for url in urls:
        listing_id = extract_listing_id(url)
        if listing_id is None:
            continue
        seen_listing_ids.append(listing_id)
        records.append(
            {
                "listing_id": listing_id,
                "url": url,
                "listing_type": infer_listing_type_from_url(url),
                "search_category": search_category,
            }
        )

    if HREFS_PATH:
        HREFS_PATH.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")

    inserted = upsert_many_discovered_listings(records)
    mark_missing_listings_inactive(seen_listing_ids, search_category=search_category)
    return inserted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover listing URLs from batdongsan.com.vn")
    parser.add_argument("--base-url", default=DEFAULT_DISCOVER_URL)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless")
    parser.add_argument(
        "--disable-recent-stop",
        action="store_true",
        help="Do not stop discovery when the crawler loops back to recently scraped listings",
    )
    parser.add_argument(
        "--recent-window",
        type=int,
        default=100,
        help="How many recently scraped listing IDs to use for early-stop detection",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = time.time()
    urls = discover_all(
        base_url=args.base_url,
        max_pages=args.max_pages,
        headless=args.headless,
        stop_when_reaching_recent=not args.disable_recent_stop,
        recent_window=args.recent_window,
    )
    saved = persist_discovered_urls(urls)
    print(f"Discovered {len(urls)} urls, persisted {saved} rows in {time.time() - started_at:.1f}s")


if __name__ == "__main__":
    main()
