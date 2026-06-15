from __future__ import annotations

import argparse

from hanoi_real_estate.config import DEFAULT_SEARCH_CATEGORY, DEFAULT_SOURCE_SITE
from hanoi_real_estate.db import init_db
from hanoi_real_estate.parsers import extract_listing_id, infer_listing_type_from_url
from hanoi_real_estate.repository import count_pending_listings, upsert_many_seed_listings


def load_urls(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as file:
        seen: dict[str, None] = {}
        for line in file:
            url = line.strip()
            if not url or "batdongsan.com.vn" not in url:
                continue
            seen[url] = None
    return list(seen.keys())


def build_records(urls: list[str], search_category: str) -> list[dict[str, str | None]]:
    records: list[dict[str, str | None]] = []
    for url in urls:
        listing_id = extract_listing_id(url)
        if listing_id is None:
            continue
        records.append(
            {
                "listing_id": listing_id,
                "url": url,
                "listing_type": infer_listing_type_from_url(url),
                "search_category": search_category,
                "source_site": DEFAULT_SOURCE_SITE,
            }
        )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import href text file into SQLite listing queue")
    parser.add_argument("path", help="Path to href text file, e.g. hrefs_old.txt")
    parser.add_argument("--search-category", default=DEFAULT_SEARCH_CATEGORY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_db()
    urls = load_urls(args.path)
    records = build_records(urls, args.search_category)
    inserted = upsert_many_seed_listings(records)
    print(f"Imported {inserted} URLs from {args.path}")
    print(f"Pending listings in queue: {count_pending_listings()}")


if __name__ == "__main__":
    main()
