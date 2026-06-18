from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sqlalchemy import text

from hanoi_real_estate.config import DB_PATH
from hanoi_real_estate.db import get_engine, init_db


TABLE_ORDER = [
    "listing",
    "listing_current",
    "address",
    "listing_history",
    "scrape_errors",
]


UPSERT_SQL = {
    "listing": """
        INSERT INTO listing (
            listing_id, url, source_site, listing_type, search_category,
            first_seen_at, last_seen_at, last_detail_requested_at, last_detail_scraped_at,
            status, failure_count, is_active, notes
        )
        VALUES (
            :listing_id, :url, :source_site, :listing_type, :search_category,
            :first_seen_at, :last_seen_at, :last_detail_requested_at, :last_detail_scraped_at,
            :status, :failure_count, :is_active, :notes
        )
        ON CONFLICT (listing_id) DO UPDATE SET
            url = excluded.url,
            source_site = excluded.source_site,
            listing_type = excluded.listing_type,
            search_category = excluded.search_category,
            first_seen_at = excluded.first_seen_at,
            last_seen_at = excluded.last_seen_at,
            last_detail_requested_at = excluded.last_detail_requested_at,
            last_detail_scraped_at = excluded.last_detail_scraped_at,
            status = excluded.status,
            failure_count = excluded.failure_count,
            is_active = excluded.is_active,
            notes = excluded.notes
    """,
    "listing_current": """
        INSERT INTO listing_current (
            listing_id, title, title_normalized, price_raw, price_value_vnd,
            price_value_billion_vnd, price_per_m2_raw, price_per_m2_value_million_vnd,
            bedrooms, area_raw, area_m2, front_length_m, road_size_m, direction,
            balcony_direction, floors, toilets, legal_status, published_at, expired_at,
            ad_type, raw_district, last_scraped_at, content_hash
        )
        VALUES (
            :listing_id, :title, :title_normalized, :price_raw, :price_value_vnd,
            :price_value_billion_vnd, :price_per_m2_raw, :price_per_m2_value_million_vnd,
            :bedrooms, :area_raw, :area_m2, :front_length_m, :road_size_m, :direction,
            :balcony_direction, :floors, :toilets, :legal_status, :published_at, :expired_at,
            :ad_type, :raw_district, :last_scraped_at, :content_hash
        )
        ON CONFLICT (listing_id) DO UPDATE SET
            title = excluded.title,
            title_normalized = excluded.title_normalized,
            price_raw = excluded.price_raw,
            price_value_vnd = excluded.price_value_vnd,
            price_value_billion_vnd = excluded.price_value_billion_vnd,
            price_per_m2_raw = excluded.price_per_m2_raw,
            price_per_m2_value_million_vnd = excluded.price_per_m2_value_million_vnd,
            bedrooms = excluded.bedrooms,
            area_raw = excluded.area_raw,
            area_m2 = excluded.area_m2,
            front_length_m = excluded.front_length_m,
            road_size_m = excluded.road_size_m,
            direction = excluded.direction,
            balcony_direction = excluded.balcony_direction,
            floors = excluded.floors,
            toilets = excluded.toilets,
            legal_status = excluded.legal_status,
            published_at = excluded.published_at,
            expired_at = excluded.expired_at,
            ad_type = excluded.ad_type,
            raw_district = excluded.raw_district,
            last_scraped_at = excluded.last_scraped_at,
            content_hash = excluded.content_hash
    """,
    "address": """
        INSERT INTO address (
            listing_id, full_address, address_line_1, address_line_2, ward, district,
            city, latitude, longitude, location_source, last_geocoded_at
        )
        VALUES (
            :listing_id, :full_address, :address_line_1, :address_line_2, :ward, :district,
            :city, :latitude, :longitude, :location_source, :last_geocoded_at
        )
        ON CONFLICT (listing_id) DO UPDATE SET
            full_address = excluded.full_address,
            address_line_1 = excluded.address_line_1,
            address_line_2 = excluded.address_line_2,
            ward = excluded.ward,
            district = excluded.district,
            city = excluded.city,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            location_source = excluded.location_source,
            last_geocoded_at = excluded.last_geocoded_at
    """,
    "listing_history": """
        INSERT INTO listing_history (
            id, listing_id, scraped_at, price_raw, price_value_vnd, price_per_m2_raw,
            price_per_m2_value_million_vnd, expired_at, ad_type, is_active, content_hash
        )
        VALUES (
            :id, :listing_id, :scraped_at, :price_raw, :price_value_vnd, :price_per_m2_raw,
            :price_per_m2_value_million_vnd, :expired_at, :ad_type, :is_active, :content_hash
        )
        ON CONFLICT (id) DO UPDATE SET
            listing_id = excluded.listing_id,
            scraped_at = excluded.scraped_at,
            price_raw = excluded.price_raw,
            price_value_vnd = excluded.price_value_vnd,
            price_per_m2_raw = excluded.price_per_m2_raw,
            price_per_m2_value_million_vnd = excluded.price_per_m2_value_million_vnd,
            expired_at = excluded.expired_at,
            ad_type = excluded.ad_type,
            is_active = excluded.is_active,
            content_hash = excluded.content_hash
    """,
    "scrape_errors": """
        INSERT INTO scrape_errors (
            id, listing_id, stage, error_type, error_message, happened_at, retryable
        )
        VALUES (
            :id, :listing_id, :stage, :error_type, :error_message, :happened_at, :retryable
        )
        ON CONFLICT (id) DO UPDATE SET
            listing_id = excluded.listing_id,
            stage = excluded.stage,
            error_type = excluded.error_type,
            error_message = excluded.error_message,
            happened_at = excluded.happened_at,
            retryable = excluded.retryable
    """,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy local SQLite data into PostgreSQL.")
    parser.add_argument("--sqlite-path", default=str(DB_PATH))
    parser.add_argument("--batch-size", type=int, default=1000)
    return parser.parse_args()


def fetch_rows(conn: sqlite3.Connection, table_name: str, offset: int, limit: int) -> list[dict[str, object]]:
    rows = conn.execute(
        f"SELECT * FROM {table_name} ORDER BY rowid LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def sync_table(sqlite_conn: sqlite3.Connection, table_name: str, batch_size: int) -> int:
    total = 0
    offset = 0
    insert_sql = text(UPSERT_SQL[table_name])
    engine = get_engine()
    while True:
        batch = fetch_rows(sqlite_conn, table_name, offset, batch_size)
        if not batch:
            break
        with engine.begin() as pg_conn:
            pg_conn.execute(insert_sql, batch)
        total += len(batch)
        offset += batch_size
        print(f"{table_name}: synced {total}")
    return total


def main() -> None:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    init_db()

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        for table_name in TABLE_ORDER:
            total = sync_table(sqlite_conn, table_name, args.batch_size)
            print(f"{table_name}: complete ({total} rows)")
    finally:
        sqlite_conn.close()

    with get_engine().connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) AS count FROM listing"))
        listing_count = result.scalar_one()
    print(f"PostgreSQL listing count: {listing_count}")


if __name__ == "__main__":
    main()
