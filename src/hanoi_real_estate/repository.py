from __future__ import annotations

import sqlite3
from typing import Iterable

from .config import DEFAULT_SEARCH_CATEGORY, DEFAULT_SOURCE_SITE
from .db import get_connection


def upsert_discovered_listing(
    listing_id: str,
    url: str,
    listing_type: str | None,
    search_category: str = DEFAULT_SEARCH_CATEGORY,
    source_site: str = DEFAULT_SOURCE_SITE,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO listing (
                listing_id,
                url,
                source_site,
                listing_type,
                search_category,
                first_seen_at,
                last_seen_at,
                status,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'new', 1)
            ON CONFLICT(listing_id) DO UPDATE SET
                url = excluded.url,
                source_site = excluded.source_site,
                listing_type = COALESCE(excluded.listing_type, listing.listing_type),
                search_category = COALESCE(excluded.search_category, listing.search_category),
                last_seen_at = CURRENT_TIMESTAMP,
                is_active = 1,
                status = CASE
                    WHEN listing.status = 'done' THEN listing.status
                    WHEN listing.status = 'queued' THEN listing.status
                    ELSE 'new'
                END
            """,
            (listing_id, url, source_site, listing_type, search_category),
        )


def upsert_many_discovered_listings(records: Iterable[dict[str, str | None]]) -> int:
    inserted = 0
    with get_connection() as conn:
        for record in records:
            conn.execute(
                """
                INSERT INTO listing (
                    listing_id,
                    url,
                    source_site,
                    listing_type,
                    search_category,
                    first_seen_at,
                    last_seen_at,
                    status,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'new', 1)
                ON CONFLICT(listing_id) DO UPDATE SET
                    url = excluded.url,
                    source_site = excluded.source_site,
                    listing_type = COALESCE(excluded.listing_type, listing.listing_type),
                    search_category = COALESCE(excluded.search_category, listing.search_category),
                    last_seen_at = CURRENT_TIMESTAMP,
                    is_active = 1
                """,
                (
                    record["listing_id"],
                    record["url"],
                    record.get("source_site", DEFAULT_SOURCE_SITE),
                    record.get("listing_type"),
                    record.get("search_category", DEFAULT_SEARCH_CATEGORY),
                ),
            )
            inserted += 1
    return inserted


def upsert_many_seed_listings(records: Iterable[dict[str, str | None]]) -> int:
    inserted = 0
    with get_connection() as conn:
        for record in records:
            conn.execute(
                """
                INSERT INTO listing (
                    listing_id,
                    url,
                    source_site,
                    listing_type,
                    search_category,
                    first_seen_at,
                    last_seen_at,
                    status,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'new', 1)
                ON CONFLICT(listing_id) DO UPDATE SET
                    url = excluded.url,
                    source_site = excluded.source_site,
                    listing_type = COALESCE(excluded.listing_type, listing.listing_type),
                    search_category = COALESCE(excluded.search_category, listing.search_category),
                    last_seen_at = CURRENT_TIMESTAMP,
                    is_active = 1,
                    status = CASE
                        WHEN listing.status = 'done' THEN listing.status
                        WHEN listing.status = 'queued' THEN listing.status
                        WHEN listing.status = 'failed' THEN listing.status
                        ELSE 'new'
                    END
                """,
                (
                    record["listing_id"],
                    record["url"],
                    record.get("source_site", DEFAULT_SOURCE_SITE),
                    record.get("listing_type"),
                    record.get("search_category", DEFAULT_SEARCH_CATEGORY),
                ),
            )
            inserted += 1
    return inserted


def mark_missing_listings_inactive(seen_listing_ids: Iterable[str], search_category: str = DEFAULT_SEARCH_CATEGORY) -> int:
    ids = list(seen_listing_ids)
    with get_connection() as conn:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            query = f"""
                UPDATE listing
                SET is_active = 0, status = 'inactive'
                WHERE search_category = ?
                  AND listing_id NOT IN ({placeholders})
            """
            cursor = conn.execute(query, [search_category, *ids])
        else:
            cursor = conn.execute(
                """
                UPDATE listing
                SET is_active = 0, status = 'inactive'
                WHERE search_category = ?
                """,
                (search_category,),
            )
        return cursor.rowcount


def fetch_pending_listing_urls(limit: int = 50) -> list[sqlite3.Row]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT listing_id, url
            FROM listing
            WHERE is_active = 1
              AND status IN ('new', 'failed', 'queued')
            ORDER BY
                CASE status
                    WHEN 'new' THEN 0
                    WHEN 'failed' THEN 1
                    ELSE 2
                END,
                COALESCE(last_detail_scraped_at, first_seen_at) ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if rows:
            conn.executemany(
                """
                UPDATE listing
                SET status = 'queued',
                    last_detail_requested_at = CURRENT_TIMESTAMP
                WHERE listing_id = ?
                """,
                [(row["listing_id"],) for row in rows],
            )
        return rows


def fetch_recent_scraped_listing_ids(limit: int = 200) -> set[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT listing_id
            FROM listing
            WHERE last_detail_scraped_at IS NOT NULL
            ORDER BY last_detail_scraped_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {str(row["listing_id"]) for row in rows}


def mark_listing_failed(listing_id: str, error_type: str, error_message: str, stage: str = "detail", retryable: bool = True) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE listing
            SET status = 'failed',
                failure_count = failure_count + 1
            WHERE listing_id = ?
            """,
            (listing_id,),
        )
        conn.execute(
            """
            INSERT INTO scrape_errors (listing_id, stage, error_type, error_message, retryable)
            VALUES (?, ?, ?, ?, ?)
            """,
            (listing_id, stage, error_type, error_message[:2000], 1 if retryable else 0),
        )


def save_listing_detail(payload: dict[str, dict[str, object]]) -> None:
    listing = payload["listing"]
    current = payload["listing_current"]
    address = payload["address"]
    history = payload["history"]

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO listing (
                listing_id,
                url,
                listing_type,
                source_site,
                search_category,
                first_seen_at,
                last_seen_at,
                status,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(listing_id) DO UPDATE SET
                url = excluded.url,
                listing_type = COALESCE(excluded.listing_type, listing.listing_type),
                last_seen_at = CURRENT_TIMESTAMP,
                last_detail_scraped_at = CURRENT_TIMESTAMP,
                status = excluded.status,
                is_active = excluded.is_active,
                failure_count = 0
            """,
            (
                listing["listing_id"],
                listing["url"],
                listing.get("listing_type"),
                DEFAULT_SOURCE_SITE,
                DEFAULT_SEARCH_CATEGORY,
                listing.get("status", "done"),
                listing.get("is_active", 1),
            ),
        )
        conn.execute(
            """
            UPDATE listing
            SET last_detail_scraped_at = CURRENT_TIMESTAMP,
                status = ?,
                is_active = ?,
                failure_count = 0
            WHERE listing_id = ?
            """,
            (listing.get("status", "done"), listing.get("is_active", 1), listing["listing_id"]),
        )
        conn.execute(
            """
            INSERT INTO listing_current (
                listing_id,
                title,
                title_normalized,
                price_raw,
                price_value_vnd,
                price_value_billion_vnd,
                price_per_m2_raw,
                price_per_m2_value_million_vnd,
                bedrooms,
                area_raw,
                area_m2,
                front_length_m,
                road_size_m,
                direction,
                balcony_direction,
                floors,
                toilets,
                legal_status,
                published_at,
                expired_at,
                ad_type,
                raw_district,
                last_scraped_at,
                content_hash
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CURRENT_TIMESTAMP, ?
            )
            ON CONFLICT(listing_id) DO UPDATE SET
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
                last_scraped_at = CURRENT_TIMESTAMP,
                content_hash = excluded.content_hash
            """,
            (
                current["listing_id"],
                current.get("title"),
                current.get("title_normalized"),
                current.get("price_raw"),
                current.get("price_value_vnd"),
                current.get("price_value_billion_vnd"),
                current.get("price_per_m2_raw"),
                current.get("price_per_m2_value_million_vnd"),
                current.get("bedrooms"),
                current.get("area_raw"),
                current.get("area_m2"),
                current.get("front_length_m"),
                current.get("road_size_m"),
                current.get("direction"),
                current.get("balcony_direction"),
                current.get("floors"),
                current.get("toilets"),
                current.get("legal_status"),
                current.get("published_at"),
                current.get("expired_at"),
                current.get("ad_type"),
                current.get("raw_district"),
                current.get("content_hash"),
            ),
        )
        conn.execute(
            """
            INSERT INTO address (
                listing_id,
                full_address,
                address_line_1,
                address_line_2,
                ward,
                district,
                city,
                latitude,
                longitude,
                location_source,
                last_geocoded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(listing_id) DO UPDATE SET
                full_address = excluded.full_address,
                address_line_1 = excluded.address_line_1,
                address_line_2 = excluded.address_line_2,
                ward = excluded.ward,
                district = COALESCE(excluded.district, address.district),
                city = COALESCE(excluded.city, address.city),
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                location_source = excluded.location_source,
                last_geocoded_at = excluded.last_geocoded_at
            """,
            (
                address["listing_id"],
                address.get("full_address"),
                address.get("address_line_1"),
                address.get("address_line_2"),
                address.get("ward"),
                address.get("district"),
                address.get("city"),
                address.get("latitude"),
                address.get("longitude"),
                address.get("location_source"),
                address.get("last_geocoded_at"),
            ),
        )
        conn.execute(
            """
            INSERT INTO listing_history (
                listing_id,
                scraped_at,
                price_raw,
                price_value_vnd,
                price_per_m2_raw,
                price_per_m2_value_million_vnd,
                expired_at,
                ad_type,
                is_active,
                content_hash
            )
            VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history["listing_id"],
                history.get("price_raw"),
                history.get("price_value_vnd"),
                history.get("price_per_m2_raw"),
                history.get("price_per_m2_value_million_vnd"),
                history.get("expired_at"),
                history.get("ad_type"),
                history.get("is_active", 1),
                history.get("content_hash"),
            ),
        )


def count_listings() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM listing").fetchone()
        return int(row[0])


def count_pending_listings() -> int:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM listing
            WHERE is_active = 1
              AND status IN ('new', 'failed', 'queued')
            """
        ).fetchone()
        return int(row[0])
