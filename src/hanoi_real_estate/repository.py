from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text

from .config import DEFAULT_SEARCH_CATEGORY, DEFAULT_SOURCE_SITE
from .db import ensure_postgres_serial_sequence, fetch_all_rows, get_connection, get_engine, is_postgres_backend


def upsert_discovered_listing(
    listing_id: str,
    url: str,
    listing_type: str | None,
    search_category: str = DEFAULT_SEARCH_CATEGORY,
    source_site: str = DEFAULT_SOURCE_SITE,
) -> None:
    record = {
        "listing_id": listing_id,
        "url": url,
        "listing_type": listing_type,
        "search_category": search_category,
        "source_site": source_site,
    }
    upsert_many_discovered_listings([record])


def upsert_many_discovered_listings(records: Iterable[dict[str, str | None]]) -> int:
    prepared = [_prepare_seed_record(record) for record in records]
    if not prepared:
        return 0
    if is_postgres_backend():
        with get_engine().begin() as conn:
            for record in prepared:
                conn.execute(text(_POSTGRES_DISCOVER_UPSERT_SQL), record)
        return len(prepared)

    with get_connection() as conn:
        for record in prepared:
            conn.execute(
                _SQLITE_DISCOVER_UPSERT_SQL,
                (
                    record["listing_id"],
                    record["url"],
                    record["source_site"],
                    record["listing_type"],
                    record["search_category"],
                ),
            )
    return len(prepared)


def upsert_many_seed_listings(records: Iterable[dict[str, str | None]]) -> int:
    prepared = [_prepare_seed_record(record) for record in records]
    if not prepared:
        return 0
    if is_postgres_backend():
        with get_engine().begin() as conn:
            for record in prepared:
                conn.execute(text(_POSTGRES_SEED_UPSERT_SQL), record)
        return len(prepared)

    with get_connection() as conn:
        for record in prepared:
            conn.execute(
                _SQLITE_SEED_UPSERT_SQL,
                (
                    record["listing_id"],
                    record["url"],
                    record["source_site"],
                    record["listing_type"],
                    record["search_category"],
                ),
            )
    return len(prepared)


def mark_missing_listings_inactive(
    seen_listing_ids: Iterable[str],
    search_category: str = DEFAULT_SEARCH_CATEGORY,
) -> int:
    ids = [str(value) for value in seen_listing_ids]
    if is_postgres_backend():
        with get_engine().begin() as conn:
            if ids:
                result = conn.execute(
                    text(
                        """
                        UPDATE listing
                        SET is_active = 0, status = 'inactive'
                        WHERE search_category = :search_category
                          AND listing_id NOT IN (
                              SELECT UNNEST(CAST(:listing_ids AS text[]))
                          )
                        """
                    ),
                    {"search_category": search_category, "listing_ids": ids},
                )
            else:
                result = conn.execute(
                    text(
                        """
                        UPDATE listing
                        SET is_active = 0, status = 'inactive'
                        WHERE search_category = :search_category
                        """
                    ),
                    {"search_category": search_category},
                )
        return int(result.rowcount or 0)

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
        return int(cursor.rowcount)


def fetch_pending_listing_urls(limit: int = 50) -> list[sqlite3.Row | dict[str, Any]]:
    if is_postgres_backend():
        with get_engine().begin() as conn:
            rows = conn.execute(
                text(
                    """
                    WITH picked AS (
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
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE listing AS l
                    SET status = 'queued',
                        last_detail_requested_at = CURRENT_TIMESTAMP
                    FROM picked
                    WHERE l.listing_id = picked.listing_id
                    RETURNING picked.listing_id, picked.url
                    """
                ),
                {"limit": limit},
            )
            return rows.mappings().all()

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
    rows = fetch_all_rows(
        """
        SELECT listing_id
        FROM listing
        WHERE last_detail_scraped_at IS NOT NULL
        ORDER BY last_detail_scraped_at DESC
        LIMIT :limit
        """ if is_postgres_backend() else """
        SELECT listing_id
        FROM listing
        WHERE last_detail_scraped_at IS NOT NULL
        ORDER BY last_detail_scraped_at DESC
        LIMIT ?
        """,
        {"limit": limit} if is_postgres_backend() else (limit,),
    )
    return {str(row["listing_id"]) for row in rows}


def fetch_existing_listing_ids(listing_ids: Iterable[str]) -> set[str]:
    ids = [str(value) for value in listing_ids if value]
    if not ids:
        return set()
    if is_postgres_backend():
        rows = fetch_all_rows(
            """
            SELECT listing_id
            FROM listing
            WHERE listing_id = ANY(CAST(:listing_ids AS text[]))
            """,
            {"listing_ids": ids},
        )
        return {str(row["listing_id"]) for row in rows}

    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT listing_id
            FROM listing
            WHERE listing_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    return {str(row["listing_id"]) for row in rows}


def mark_listing_failed(
    listing_id: str,
    error_type: str,
    error_message: str,
    stage: str = "detail",
    retryable: bool = True,
) -> None:
    if is_postgres_backend():
        ensure_postgres_serial_sequence("scrape_errors", "id")
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE listing
                    SET status = 'failed',
                        failure_count = failure_count + 1
                    WHERE listing_id = :listing_id
                    """
                ),
                {"listing_id": listing_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO scrape_errors (listing_id, stage, error_type, error_message, retryable)
                    VALUES (:listing_id, :stage, :error_type, :error_message, :retryable)
                    """
                ),
                {
                    "listing_id": listing_id,
                    "stage": stage,
                    "error_type": error_type,
                    "error_message": error_message[:2000],
                    "retryable": 1 if retryable else 0,
                },
            )
        return

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

    if is_postgres_backend():
        ensure_postgres_serial_sequence("listing_history", "id")
        with get_engine().begin() as conn:
            conn.execute(text(_POSTGRES_SAVE_LISTING_SQL), _listing_params(listing))
            conn.execute(text(_POSTGRES_TOUCH_LISTING_SQL), _touch_listing_params(listing))
            conn.execute(text(_POSTGRES_SAVE_LISTING_CURRENT_SQL), _listing_current_params(current))
            conn.execute(text(_POSTGRES_SAVE_ADDRESS_SQL), _address_params(address))
            conn.execute(text(_POSTGRES_SAVE_HISTORY_SQL), _history_params(history))
        return

    with get_connection() as conn:
        conn.execute(
            _SQLITE_SAVE_LISTING_SQL,
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
            _SQLITE_SAVE_LISTING_CURRENT_SQL,
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
            _SQLITE_SAVE_ADDRESS_SQL,
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
    rows = fetch_all_rows("SELECT COUNT(*) AS count FROM listing")
    return int(rows[0]["count"]) if rows else 0


def count_pending_listings() -> int:
    rows = fetch_all_rows(
        """
        SELECT COUNT(*) AS count
        FROM listing
        WHERE is_active = 1
          AND status IN ('new', 'failed', 'queued')
        """
    )
    return int(rows[0]["count"]) if rows else 0


def _prepare_seed_record(record: dict[str, str | None]) -> dict[str, str | None]:
    return {
        "listing_id": record["listing_id"],
        "url": record["url"],
        "source_site": record.get("source_site", DEFAULT_SOURCE_SITE),
        "listing_type": record.get("listing_type"),
        "search_category": record.get("search_category", DEFAULT_SEARCH_CATEGORY),
    }


def _listing_params(listing: dict[str, object]) -> dict[str, object]:
    return {
        "listing_id": listing["listing_id"],
        "url": listing["url"],
        "listing_type": listing.get("listing_type"),
        "source_site": DEFAULT_SOURCE_SITE,
        "search_category": DEFAULT_SEARCH_CATEGORY,
        "status": listing.get("status", "done"),
        "is_active": listing.get("is_active", 1),
    }


def _touch_listing_params(listing: dict[str, object]) -> dict[str, object]:
    return {
        "listing_id": listing["listing_id"],
        "status": listing.get("status", "done"),
        "is_active": listing.get("is_active", 1),
    }


def _listing_current_params(current: dict[str, object]) -> dict[str, object]:
    return {
        "listing_id": current["listing_id"],
        "title": current.get("title"),
        "title_normalized": current.get("title_normalized"),
        "price_raw": current.get("price_raw"),
        "price_value_vnd": current.get("price_value_vnd"),
        "price_value_billion_vnd": current.get("price_value_billion_vnd"),
        "price_per_m2_raw": current.get("price_per_m2_raw"),
        "price_per_m2_value_million_vnd": current.get("price_per_m2_value_million_vnd"),
        "bedrooms": current.get("bedrooms"),
        "area_raw": current.get("area_raw"),
        "area_m2": current.get("area_m2"),
        "front_length_m": current.get("front_length_m"),
        "road_size_m": current.get("road_size_m"),
        "direction": current.get("direction"),
        "balcony_direction": current.get("balcony_direction"),
        "floors": current.get("floors"),
        "toilets": current.get("toilets"),
        "legal_status": current.get("legal_status"),
        "published_at": current.get("published_at"),
        "expired_at": current.get("expired_at"),
        "ad_type": current.get("ad_type"),
        "raw_district": current.get("raw_district"),
        "content_hash": current.get("content_hash"),
    }


def _address_params(address: dict[str, object]) -> dict[str, object]:
    return {
        "listing_id": address["listing_id"],
        "full_address": address.get("full_address"),
        "address_line_1": address.get("address_line_1"),
        "address_line_2": address.get("address_line_2"),
        "ward": address.get("ward"),
        "district": address.get("district"),
        "city": address.get("city"),
        "latitude": address.get("latitude"),
        "longitude": address.get("longitude"),
        "location_source": address.get("location_source"),
        "last_geocoded_at": address.get("last_geocoded_at"),
    }


def _history_params(history: dict[str, object]) -> dict[str, object]:
    return {
        "listing_id": history["listing_id"],
        "price_raw": history.get("price_raw"),
        "price_value_vnd": history.get("price_value_vnd"),
        "price_per_m2_raw": history.get("price_per_m2_raw"),
        "price_per_m2_value_million_vnd": history.get("price_per_m2_value_million_vnd"),
        "expired_at": history.get("expired_at"),
        "ad_type": history.get("ad_type"),
        "is_active": history.get("is_active", 1),
        "content_hash": history.get("content_hash"),
    }


_SQLITE_DISCOVER_UPSERT_SQL = """
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
"""


_SQLITE_SEED_UPSERT_SQL = """
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
"""


_POSTGRES_DISCOVER_UPSERT_SQL = """
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
VALUES (:listing_id, :url, :source_site, :listing_type, :search_category, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'new', 1)
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
"""


_POSTGRES_SEED_UPSERT_SQL = """
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
VALUES (:listing_id, :url, :source_site, :listing_type, :search_category, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'new', 1)
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
"""


_SQLITE_SAVE_LISTING_SQL = """
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
"""


_POSTGRES_SAVE_LISTING_SQL = """
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
VALUES (:listing_id, :url, :listing_type, :source_site, :search_category, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :status, :is_active)
ON CONFLICT(listing_id) DO UPDATE SET
    url = excluded.url,
    listing_type = COALESCE(excluded.listing_type, listing.listing_type),
    last_seen_at = CURRENT_TIMESTAMP,
    last_detail_scraped_at = CURRENT_TIMESTAMP,
    status = excluded.status,
    is_active = excluded.is_active,
    failure_count = 0
"""


_POSTGRES_TOUCH_LISTING_SQL = """
UPDATE listing
SET last_detail_scraped_at = CURRENT_TIMESTAMP,
    status = :status,
    is_active = :is_active,
    failure_count = 0
WHERE listing_id = :listing_id
"""


_SQLITE_SAVE_LISTING_CURRENT_SQL = """
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
"""


_POSTGRES_SAVE_LISTING_CURRENT_SQL = """
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
    :listing_id, :title, :title_normalized, :price_raw, :price_value_vnd, :price_value_billion_vnd,
    :price_per_m2_raw, :price_per_m2_value_million_vnd, :bedrooms, :area_raw, :area_m2, :front_length_m,
    :road_size_m, :direction, :balcony_direction, :floors, :toilets, :legal_status, :published_at,
    :expired_at, :ad_type, :raw_district, CURRENT_TIMESTAMP, :content_hash
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
"""


_SQLITE_SAVE_ADDRESS_SQL = """
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
"""


_POSTGRES_SAVE_ADDRESS_SQL = """
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
VALUES (:listing_id, :full_address, :address_line_1, :address_line_2, :ward, :district, :city, :latitude, :longitude, :location_source, :last_geocoded_at)
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
"""


_POSTGRES_SAVE_HISTORY_SQL = """
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
VALUES (:listing_id, CURRENT_TIMESTAMP, :price_raw, :price_value_vnd, :price_per_m2_raw, :price_per_m2_value_million_vnd, :expired_at, :ad_type, :is_active, :content_hash)
"""
