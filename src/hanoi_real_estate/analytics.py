from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .db import get_connection


THAP_RUA_LAT = 21.0255923
THAP_RUA_LON = 105.8464321


def load_dashboard_dataframe(active_only: bool = True) -> pd.DataFrame:
    where_clause = "WHERE l.is_active = 1" if active_only else ""
    query = f"""
        SELECT
            l.listing_id,
            l.url,
            l.status,
            l.is_active,
            l.first_seen_at,
            l.last_seen_at,
            lc.title,
            lc.price_raw,
            lc.price_value_vnd,
            lc.price_value_billion_vnd,
            lc.price_per_m2_raw,
            lc.price_per_m2_value_million_vnd,
            lc.bedrooms,
            lc.area_raw,
            lc.area_m2,
            lc.front_length_m,
            lc.road_size_m,
            lc.direction,
            lc.balcony_direction,
            lc.floors,
            lc.toilets,
            lc.legal_status,
            lc.published_at,
            lc.expired_at,
            lc.ad_type,
            lc.raw_district,
            lc.last_scraped_at,
            a.full_address,
            a.address_line_1,
            a.address_line_2,
            a.ward,
            a.district,
            a.city,
            a.latitude,
            a.longitude
        FROM listing l
        LEFT JOIN listing_current lc ON lc.listing_id = l.listing_id
        LEFT JOIN address a ON a.listing_id = l.listing_id
        {where_clause}
        ORDER BY COALESCE(lc.published_at, l.last_seen_at) DESC, l.listing_id DESC
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)

    if df.empty:
        return pd.DataFrame(columns=_dashboard_columns())

    return prepare_dashboard_dataframe(df)


def prepare_dashboard_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()

    working["Mã tin"] = working["listing_id"].astype(str)
    working["Link"] = working["url"]
    working["Tiêu đề"] = working["title"]
    working["Địa chỉ"] = working["full_address"]
    working["Địa chỉ 1"] = working["address_line_1"]
    working["Địa chỉ 2"] = working["address_line_2"]
    working["Mức giá"] = working.apply(_display_total_price, axis=1)
    working["Giá/m²"] = working.apply(_display_price_per_m2, axis=1)
    working["Số phòng ngủ"] = working["bedrooms"]
    working["Huyện"] = working["raw_district"].fillna(working["district"])
    working["Diện tích"] = working.apply(
        lambda row: _display_metric(row.get("area_raw"), row.get("area_m2"), "m²"),
        axis=1,
    )
    working["Mặt tiền"] = working.apply(
        lambda row: _display_metric(None, row.get("front_length_m"), "m"),
        axis=1,
    )
    working["Đường vào"] = working.apply(
        lambda row: _display_metric(None, row.get("road_size_m"), "m"),
        axis=1,
    )
    working["Hướng nhà"] = working["direction"]
    working["Hướng ban công"] = working["balcony_direction"]
    working["Số tầng"] = working["floors"].apply(_display_integer_metric)
    working["Số toilet"] = working["toilets"].apply(_display_integer_metric)
    working["Pháp lý"] = working["legal_status"]
    working["Ngày đăng"] = working["published_at"].apply(_iso_to_ddmmyyyy)
    working["Ngày hết hạn"] = working["expired_at"].apply(_iso_to_ddmmyyyy)
    working["Loại tin"] = working["ad_type"]
    working["Latitude"] = pd.to_numeric(working["latitude"], errors="coerce")
    working["Longitude"] = pd.to_numeric(working["longitude"], errors="coerce")

    working["Mức giá trị"] = pd.to_numeric(working["price_value_billion_vnd"], errors="coerce")
    working["Giá/m² trị"] = pd.to_numeric(working["price_per_m2_value_million_vnd"], errors="coerce")
    working["Diện tích trị"] = pd.to_numeric(working["area_m2"], errors="coerce")
    working["dist_to_HN_center"] = working.apply(
        lambda row: haversine_km(
            row.get("Latitude"),
            row.get("Longitude"),
            THAP_RUA_LAT,
            THAP_RUA_LON,
        ),
        axis=1,
    )
    working["direction_to_HN_center"] = working.apply(
        lambda row: bearing_to_direction(
            bearing_degrees(
                THAP_RUA_LAT,
                THAP_RUA_LON,
                row.get("Latitude"),
                row.get("Longitude"),
            )
        ),
        axis=1,
    )

    return working


def build_table_dataframe(active_only: bool = True) -> pd.DataFrame:
    df = load_dashboard_dataframe(active_only=active_only)
    if df.empty:
        return df
    columns = [
        "Mã tin",
        "Tiêu đề",
        "Địa chỉ",
        "Địa chỉ 1",
        "Địa chỉ 2",
        "Mức giá",
        "Giá/m²",
        "Số phòng ngủ",
        "Huyện",
        "Diện tích",
        "Mặt tiền",
        "Đường vào",
        "Hướng nhà",
        "Hướng ban công",
        "Số tầng",
        "Số toilet",
        "Pháp lý",
        "Ngày đăng",
        "Ngày hết hạn",
        "Loại tin",
        "Latitude",
        "Longitude",
        "Link",
    ]
    return df[columns]


def build_correlation_dataframe(active_only: bool = True) -> pd.DataFrame:
    df = load_dashboard_dataframe(active_only=active_only)
    if df.empty:
        return pd.DataFrame(
            columns=["dist_to_HN_center", "Giá/m²", "Latitude", "Longitude", "Địa chỉ", "Mã tin"]
        )

    plot_df = df[
        ["dist_to_HN_center", "Giá/m² trị", "Latitude", "Longitude", "Địa chỉ", "Mã tin"]
    ].copy()
    plot_df = plot_df.rename(columns={"Giá/m² trị": "Giá/m²"})
    plot_df["dist_to_HN_center"] = pd.to_numeric(plot_df["dist_to_HN_center"], errors="coerce")
    plot_df["Giá/m²"] = pd.to_numeric(plot_df["Giá/m²"], errors="coerce")
    plot_df["Latitude"] = pd.to_numeric(plot_df["Latitude"], errors="coerce")
    plot_df["Longitude"] = pd.to_numeric(plot_df["Longitude"], errors="coerce")

    plot_df = plot_df.dropna(subset=["dist_to_HN_center", "Giá/m²", "Latitude", "Longitude", "Địa chỉ"])
    plot_df = plot_df[plot_df["dist_to_HN_center"] < 80]
    plot_df = plot_df.drop_duplicates(subset=["Latitude", "Longitude", "Địa chỉ"])
    plot_df = plot_df[plot_df["Giá/m²"] > 0]
    return plot_df.reset_index(drop=True)


def build_region_stats_dataframe(active_only: bool = True) -> pd.DataFrame:
    df = load_dashboard_dataframe(active_only=active_only)
    if df.empty:
        return pd.DataFrame(
            columns=["Huyện", "avg_price_billion_vnd", "avg_price_per_m2_million_vnd", "listing_count"]
        )

    stats_df = df.copy()
    stats_df["Mức giá trị"] = pd.to_numeric(stats_df["Mức giá trị"], errors="coerce")
    stats_df["Giá/m² trị"] = pd.to_numeric(stats_df["Giá/m² trị"], errors="coerce")
    stats_df["Huyện"] = stats_df["Huyện"].fillna("Chưa rõ")

    grouped = (
        stats_df.groupby("Huyện", dropna=False)
        .agg(
            avg_price_billion_vnd=("Mức giá trị", "mean"),
            avg_price_per_m2_million_vnd=("Giá/m² trị", "mean"),
            listing_count=("Mã tin", "count"),
        )
        .reset_index()
    )
    grouped = grouped.sort_values(
        by=["avg_price_per_m2_million_vnd", "listing_count"],
        ascending=[False, False],
    )
    return grouped.reset_index(drop=True)


def build_price_per_m2_by_region_dataframe(active_only: bool = True) -> pd.DataFrame:
    stats = build_region_stats_dataframe(active_only=active_only)
    if stats.empty:
        return stats
    return stats[["Huyện", "avg_price_per_m2_million_vnd", "listing_count"]].copy()


def build_total_price_by_region_dataframe(active_only: bool = True) -> pd.DataFrame:
    stats = build_region_stats_dataframe(active_only=active_only)
    if stats.empty:
        return stats
    return stats[["Huyện", "avg_price_billion_vnd", "listing_count"]].copy()


def haversine_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> float:
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
        return math.nan

    r = 6371.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def bearing_degrees(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> float:
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
        return math.nan

    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dlambda = math.radians(float(lon2) - float(lon1))

    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bearing_to_direction(bearing: Any) -> str | pd.NA:
    if pd.isna(bearing):
        return pd.NA

    directions = [
        "North",
        "Northeast",
        "East",
        "Southeast",
        "South",
        "Southwest",
        "West",
        "Northwest",
    ]
    index = int((float(bearing) + 22.5) // 45) % 8
    return directions[index]


def _dashboard_columns() -> list[str]:
    return [
        "Mã tin",
        "Tiêu đề",
        "Địa chỉ",
        "Địa chỉ 1",
        "Địa chỉ 2",
        "Mức giá",
        "Giá/m²",
        "Số phòng ngủ",
        "Huyện",
        "Diện tích",
        "Mặt tiền",
        "Đường vào",
        "Hướng nhà",
        "Hướng ban công",
        "Số tầng",
        "Số toilet",
        "Pháp lý",
        "Ngày đăng",
        "Ngày hết hạn",
        "Loại tin",
        "Latitude",
        "Longitude",
        "Link",
    ]


def _display_total_price(row: pd.Series) -> str | None:
    raw = row.get("price_raw")
    if isinstance(raw, str) and raw.strip():
        return raw
    value = row.get("price_value_billion_vnd")
    if pd.isna(value):
        return None
    return f"{float(value):,.2f} tỷ".replace(",", "X").replace(".", ",").replace("X", ".")


def _display_price_per_m2(row: pd.Series) -> str | None:
    raw = row.get("price_per_m2_raw")
    if isinstance(raw, str) and raw.strip():
        return raw
    value = row.get("price_per_m2_value_million_vnd")
    if pd.isna(value):
        return None
    return f"~{float(value):,.2f} triệu/m²".replace(",", "X").replace(".", ",").replace("X", ".")


def _display_metric(raw: Any, numeric_value: Any, unit: str) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw
    if pd.isna(numeric_value):
        return None
    return f"{float(numeric_value):,.2f} {unit}".replace(",", "X").replace(".", ",").replace("X", ".")


def _display_integer_metric(value: Any) -> str | None:
    if pd.isna(value):
        return None
    return str(int(value))


def _iso_to_ddmmyyyy(value: Any) -> str | None:
    if pd.isna(value) or value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = pd.to_datetime(text, errors="raise")
    except Exception:
        return text
    return parsed.strftime("%d/%m/%Y")
