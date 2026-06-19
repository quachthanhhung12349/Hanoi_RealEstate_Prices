from __future__ import annotations

import socket
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import DATABASE_URL, DB_BACKEND, DB_PATH, SQL_DIR


def is_postgres_backend() -> bool:
    return DB_BACKEND == "postgresql"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    engine_url = _normalize_postgres_engine_url(DATABASE_URL)
    return create_engine(engine_url, pool_pre_ping=True, future=True)


def read_sql_dataframe(query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    if is_postgres_backend():
        with get_engine().connect() as conn:
            return pd.read_sql_query(text(query), conn, params=params)
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_dashboard_data_version() -> str:
    if is_postgres_backend():
        rows = fetch_all_rows(
            """
            SELECT json_build_array(
                COALESCE((SELECT MAX(last_seen_at)::text FROM listing), ''),
                COALESCE((SELECT MAX(last_scraped_at)::text FROM listing_current), ''),
                COALESCE((SELECT MAX(last_geocoded_at)::text FROM address), ''),
                (SELECT COUNT(*)::text FROM listing)
            )::text AS version
            """
        )
        return str(rows[0]["version"]) if rows else "[]"

    rows = fetch_all_rows(
        """
        SELECT json_array(
            COALESCE((SELECT MAX(last_seen_at) FROM listing), ''),
            COALESCE((SELECT MAX(last_scraped_at) FROM listing_current), ''),
            COALESCE((SELECT MAX(last_geocoded_at) FROM address), ''),
            (SELECT COUNT(*) FROM listing)
        ) AS version
        """
    )
    return str(rows[0]["version"]) if rows else "[]"


def get_gis_cache_version() -> str:
    if is_postgres_backend():
        ensure_postgres_gis_cache_tables()
        rows = fetch_all_rows(
            """
            SELECT json_build_array(
                COALESCE((SELECT MAX(updated_at)::text FROM gis_price_surface), ''),
                COALESCE((SELECT MAX(updated_at)::text FROM gis_district_price), ''),
                COALESCE((SELECT MAX(updated_at)::text FROM gis_district_choropleth), ''),
                (SELECT COUNT(*)::text FROM gis_price_surface),
                (SELECT COUNT(*)::text FROM gis_district_price),
                (SELECT COUNT(*)::text FROM gis_district_choropleth)
            )::text AS version
            """
        )
        return str(rows[0]["version"]) if rows else "[]"

    rows = fetch_all_rows(
        """
        SELECT json_array(
            '',
            '',
            '',
            0,
            0,
            0
        ) AS version
        """
    )
    return str(rows[0]["version"]) if rows else "[]"


def fetch_all_rows(query: str, params: dict[str, Any] | tuple[Any, ...] | list[Any] | None = None) -> list[Any]:
    if is_postgres_backend():
        with get_engine().connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.mappings().all()
    with get_connection() as conn:
        rows = conn.execute(query, params or ()).fetchall()
    return rows


def init_db(schema_path: Path | None = None) -> None:
    default_schema = "schema_postgres.sql" if is_postgres_backend() else "schema.sql"
    schema_file = schema_path or (SQL_DIR / default_schema)
    if is_postgres_backend():
        with get_engine().begin() as conn:
            raw_conn = conn.connection.driver_connection
            with raw_conn.cursor() as cursor:
                cursor.execute(schema_file.read_text(encoding="utf-8"))
        return

    with get_connection() as conn:
        conn.executescript(schema_file.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def ensure_postgres_gis_cache_tables() -> None:
    if not is_postgres_backend():
        return

    statements = [
        """
        CREATE TABLE IF NOT EXISTS gis_price_surface (
            id BIGSERIAL PRIMARY KEY,
            longitude DOUBLE PRECISION NOT NULL,
            latitude DOUBLE PRECISION NOT NULL,
            predicted_price_per_m2 DOUBLE PRECISION NOT NULL,
            cell_polygon TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS gis_district_price (
            district_name_normalized TEXT PRIMARY KEY,
            district_osm TEXT NOT NULL,
            avg_price_per_m2 DOUBLE PRECISION NOT NULL,
            listing_count INTEGER NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS gis_district_choropleth (
            id BIGSERIAL PRIMARY KEY,
            geojson TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_gis_price_surface_updated_at ON gis_price_surface (updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_gis_district_price_updated_at ON gis_district_price (updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_gis_district_choropleth_updated_at ON gis_district_choropleth (updated_at DESC)",
    ]
    with get_engine().begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def ensure_postgres_serial_sequence(table_name: str, column_name: str) -> None:
    if not is_postgres_backend():
        return

    allowed = {
        ("listing_history", "id"),
        ("scrape_errors", "id"),
    }
    if (table_name, column_name) not in allowed:
        raise ValueError(f"Unsupported sequence target: {table_name}.{column_name}")

    statement = f"""
        SELECT setval(
            pg_get_serial_sequence('{table_name}', '{column_name}'),
            COALESCE((SELECT MAX({column_name}) FROM {table_name}), 0) + 1,
            false
        )
    """
    with get_engine().begin() as conn:
        conn.execute(text(statement))


def _normalize_postgres_engine_url(database_url: str) -> str:
    engine_url = database_url
    if engine_url.startswith("postgresql://"):
        engine_url = engine_url.replace("postgresql://", "postgresql+psycopg://", 1)

    parsed = urlsplit(engine_url)
    if parsed.scheme != "postgresql+psycopg" or not parsed.hostname:
        return engine_url

    ipv4_host = _resolve_ipv4_address(parsed.hostname)
    if not ipv4_host:
        return engine_url

    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    connect_host = query_items.get("host")
    if not connect_host:
        query_items["host"] = parsed.hostname

    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"

    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{auth}{ipv4_host}{port}"
    query = urlencode(query_items)
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def _resolve_ipv4_address(hostname: str) -> str | None:
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return None
    for result in results:
        address = result[4][0]
        if address:
            return address
    return None
