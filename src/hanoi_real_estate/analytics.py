from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .db import read_sql_dataframe


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
        ORDER BY COALESCE(lc.published_at, CAST(l.last_seen_at AS TEXT)) DESC, l.listing_id DESC
    """
    df = read_sql_dataframe(query)

    if df.empty:
        return pd.DataFrame(columns=_dashboard_columns())

    return prepare_dashboard_dataframe(df)


def ensure_dashboard_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    if df is None:
        return load_dashboard_dataframe(active_only=active_only)
    return df.copy()


def prepare_dashboard_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()

    working["Mã tin"] = working["listing_id"].astype(str)
    working["Link"] = working["url"]
    working["Tiêu đề"] = working["title"]
    working["Địa chỉ"] = working["full_address"]
    working["Địa chỉ 1"] = working["address_line_1"]
    working["Địa chỉ 2"] = working["address_line_2"]
    working["Mức giá"] = _display_total_price_series(
        working["price_raw"],
        working["price_value_billion_vnd"],
    )
    working["Giá/m²"] = _display_price_per_m2_series(
        working["price_per_m2_raw"],
        working["price_per_m2_value_million_vnd"],
    )
    working["Số phòng ngủ"] = working["bedrooms"]
    working["Huyện"] = working["raw_district"].fillna(working["district"])
    working["Diện tích"] = _display_metric_series(
        working["area_raw"],
        working["area_m2"],
        "m²",
    )
    working["Mặt tiền"] = _display_metric_series(
        None,
        working["front_length_m"],
        "m",
    )
    working["Đường vào"] = _display_metric_series(
        None,
        working["road_size_m"],
        "m",
    )
    working["Hướng nhà"] = working["direction"]
    working["Hướng ban công"] = working["balcony_direction"]
    working["Số tầng"] = _display_integer_series(working["floors"])
    working["Số toilet"] = _display_integer_series(working["toilets"])
    working["Pháp lý"] = working["legal_status"]
    working["Ngày đăng"] = _iso_to_ddmmyyyy_series(working["published_at"])
    working["Ngày hết hạn"] = _iso_to_ddmmyyyy_series(working["expired_at"])
    working["Loại tin"] = working["ad_type"]
    working["Latitude"] = pd.to_numeric(working["latitude"], errors="coerce")
    working["Longitude"] = pd.to_numeric(working["longitude"], errors="coerce")

    working["Mức giá trị"] = pd.to_numeric(working["price_value_billion_vnd"], errors="coerce")
    working["Giá/m² trị"] = pd.to_numeric(working["price_per_m2_value_million_vnd"], errors="coerce")
    working["Diện tích trị"] = pd.to_numeric(working["area_m2"], errors="coerce")
    working["dist_to_HN_center"] = _vectorized_haversine_km(
        working["Latitude"],
        working["Longitude"],
        THAP_RUA_LAT,
        THAP_RUA_LON,
    )
    working["direction_to_HN_center"] = _vectorized_bearing_to_direction(
        working["Latitude"],
        working["Longitude"],
        THAP_RUA_LAT,
        THAP_RUA_LON,
    )

    return working


def build_table_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    df = ensure_dashboard_dataframe(df, active_only=active_only)
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


def build_correlation_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    df = ensure_dashboard_dataframe(df, active_only=active_only)
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


def build_region_stats_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    df = ensure_dashboard_dataframe(df, active_only=active_only)
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


def build_price_per_m2_by_region_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    stats = build_region_stats_dataframe(df, active_only=active_only)
    if stats.empty:
        return stats
    return stats[["Huyện", "avg_price_per_m2_million_vnd", "listing_count"]].copy()


def build_total_price_by_region_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    stats = build_region_stats_dataframe(df, active_only=active_only)
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


def _display_total_price_series(raw: pd.Series, value: pd.Series) -> pd.Series:
    return _prefer_raw_or_formatted_value(
        raw,
        value,
        lambda numeric: f"{numeric:,.2f} tỷ".replace(",", "X").replace(".", ",").replace("X", "."),
    )


def _display_price_per_m2_series(raw: pd.Series, value: pd.Series) -> pd.Series:
    return _prefer_raw_or_formatted_value(
        raw,
        value,
        lambda numeric: f"~{numeric:,.2f} triệu/m²".replace(",", "X").replace(".", ",").replace("X", "."),
    )


def _display_metric_series(raw: pd.Series | None, value: pd.Series, unit: str) -> pd.Series:
    return _prefer_raw_or_formatted_value(
        raw,
        value,
        lambda numeric: f"{numeric:,.2f} {unit}".replace(",", "X").replace(".", ",").replace("X", "."),
    )


def _prefer_raw_or_formatted_value(
    raw: pd.Series | None,
    value: pd.Series,
    formatter,
) -> pd.Series:
    numeric = pd.to_numeric(value, errors="coerce")
    formatted = numeric.map(lambda item: formatter(float(item)) if pd.notna(item) else None)
    if raw is None:
        return formatted

    raw_text = raw.astype("string").str.strip()
    has_raw = raw_text.notna() & raw_text.ne("")
    return raw_text.where(has_raw, formatted)


def _display_integer_series(value: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(value, errors="coerce")
    formatted = numeric.round().astype("Int64").astype("string")
    return formatted.mask(numeric.isna(), None)


def _iso_to_ddmmyyyy_series(value: pd.Series) -> pd.Series:
    text = value.astype("string").str.strip()
    parsed = pd.to_datetime(text, errors="coerce")
    formatted = parsed.dt.strftime("%d/%m/%Y")
    return formatted.where(parsed.notna(), text).mask(text.isna() | text.eq(""), None)


def _vectorized_haversine_km(
    latitudes: pd.Series,
    longitudes: pd.Series,
    target_latitude: float,
    target_longitude: float,
) -> pd.Series:
    lat = pd.to_numeric(latitudes, errors="coerce").to_numpy(dtype=float)
    lon = pd.to_numeric(longitudes, errors="coerce").to_numpy(dtype=float)
    valid = ~np.isnan(lat) & ~np.isnan(lon)
    distances = np.full(lat.shape, np.nan, dtype=float)
    if not valid.any():
        return pd.Series(distances, index=latitudes.index)

    lat1 = np.radians(lat[valid])
    lon1 = np.radians(lon[valid])
    lat2 = math.radians(float(target_latitude))
    lon2 = math.radians(float(target_longitude))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    distances[valid] = 2 * 6371.0 * np.arcsin(np.sqrt(a))
    return pd.Series(distances, index=latitudes.index)


def _vectorized_bearing_to_direction(
    latitudes: pd.Series,
    longitudes: pd.Series,
    target_latitude: float,
    target_longitude: float,
) -> pd.Series:
    lat = pd.to_numeric(latitudes, errors="coerce").to_numpy(dtype=float)
    lon = pd.to_numeric(longitudes, errors="coerce").to_numpy(dtype=float)
    valid = ~np.isnan(lat) & ~np.isnan(lon)
    directions = np.full(lat.shape, pd.NA, dtype=object)
    if not valid.any():
        return pd.Series(directions, index=latitudes.index, dtype="object")

    phi1 = np.radians(lat[valid])
    phi2 = math.radians(float(target_latitude))
    dlambda = math.radians(float(target_longitude)) - np.radians(lon[valid])

    x = np.sin(dlambda) * np.cos(phi2)
    y = np.cos(phi1) * np.sin(phi2) - np.sin(phi1) * np.cos(phi2) * np.cos(dlambda)
    bearing = (np.degrees(np.arctan2(x, y)) + 360) % 360
    direction_names = np.array(
        [
            "North",
            "Northeast",
            "East",
            "Southeast",
            "South",
            "Southwest",
            "West",
            "Northwest",
        ],
        dtype=object,
    )
    indices = ((bearing + 22.5) // 45).astype(int) % 8
    directions[valid] = direction_names[indices]
    return pd.Series(directions, index=latitudes.index, dtype="object")
