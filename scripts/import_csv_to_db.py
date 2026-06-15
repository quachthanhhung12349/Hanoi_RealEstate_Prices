from __future__ import annotations

import argparse
import csv

from hanoi_real_estate.config import CSV_PATH
from hanoi_real_estate.db import init_db
from hanoi_real_estate.parsers import normalize_detail_payload
from hanoi_real_estate.repository import count_listings, save_listing_detail


def iter_csv_rows(path: str):
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row_number, row in enumerate(reader, start=2):
            normalized = dict(row)
            if "\ufeffLink" in normalized and "Link" not in normalized:
                normalized["Link"] = normalized.pop("\ufeffLink")
            yield row_number, normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import scraped CSV rows into SQLite")
    parser.add_argument("--csv-path", default=str(CSV_PATH))
    parser.add_argument("--limit", type=int, default=None, help="Import only the first N rows")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_db()

    imported = 0
    failed = 0

    for row_number, row in iter_csv_rows(args.csv_path):
        if args.limit is not None and imported >= args.limit:
            break
        try:
            payload = normalize_detail_payload(row)
            save_listing_detail(payload)
            imported += 1
        except Exception as exc:
            failed += 1
            print(f"Row {row_number}: FAIL -> {exc}")

    print(f"Imported rows: {imported}")
    print(f"Failed rows: {failed}")
    print(f"Total listings in DB: {count_listings()}")


if __name__ == "__main__":
    main()
