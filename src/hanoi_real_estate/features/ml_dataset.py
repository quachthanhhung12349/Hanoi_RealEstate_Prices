from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.ops import nearest_points

from hanoi_real_estate.analytics import (
    THAP_RUA_LAT,
    THAP_RUA_LON,
    bearing_degrees,
    bearing_to_direction,
    haversine_km,
    load_dashboard_dataframe,
)
from hanoi_real_estate.gis import load_hanoi_districts, normalize_district_name
from hanoi_real_estate.parsers import clean_text


HANOI_DISTRICTS = [
    "Ba Đình",
    "Hoàn Kiếm",
    "Hai Bà Trưng",
    "Đống Đa",
    "Tây Hồ",
    "Cầu Giấy",
    "Thanh Xuân",
    "Hoàng Mai",
    "Long Biên",
    "Bắc Từ Liêm",
    "Nam Từ Liêm",
    "Hà Đông",
    "Sơn Tây",
    "Ba Vì",
    "Chương Mỹ",
    "Đan Phượng",
    "Đông Anh",
    "Gia Lâm",
    "Hoài Đức",
    "Mê Linh",
    "Mỹ Đức",
    "Phú Xuyên",
    "Phúc Thọ",
    "Quốc Oai",
    "Sóc Sơn",
    "Thạch Thất",
    "Thanh Oai",
    "Thanh Trì",
    "Thường Tín",
    "Ứng Hòa",
]

DEFAULT_DISTRICT_MISMATCH_THRESHOLD_M = 400.0
METRIC_CRS = "EPSG:3857"
WGS84_CRS = "EPSG:4326"


@dataclass(frozen=True)
class MLDatasetBuildResult:
    cleaned: pd.DataFrame
    discarded: pd.DataFrame
    summary: pd.DataFrame


def load_raw_ml_base_dataframe(active_only: bool = True) -> pd.DataFrame:
    """Load dashboard-shaped data before ML/GIS-specific cleaning."""
    return load_dashboard_dataframe(active_only=active_only)


def build_clean_ml_base_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
    mismatch_threshold_meters: float = DEFAULT_DISTRICT_MISMATCH_THRESHOLD_M,
    snap_to_stated_district: bool = True,
    keep_missing_coordinates: bool = False,
) -> MLDatasetBuildResult:
    """Prepare listing rows for later ML GIS feature engineering.

    District identity intentionally follows the listing's stated district. GIS
    polygons are used only to detect large coordinate mistakes and optionally
    snap small mistakes back to the stated district boundary.
    """
    working = load_raw_ml_base_dataframe(active_only=active_only) if df is None else df.copy()
    if working.empty:
        empty_summary = _build_summary(working, pd.DataFrame(), pd.DataFrame())
        return MLDatasetBuildResult(working, pd.DataFrame(), empty_summary)

    _ensure_required_columns(working)
    allowed_districts = _allowed_district_lookup()
    working["district_stated"] = working["Huyện"]
    working["district_stated_normalized"] = working["district_stated"].apply(normalize_district_name)
    working["district_for_ml"] = working["district_stated_normalized"].map(allowed_districts)
    if "ward" in working.columns:
        working["ward"] = working["ward"].apply(_normalize_ward_value)
    else:
        working["ward"] = pd.NA
    if working["ward"].isna().any() and "Địa chỉ" in working.columns:
        working["ward"] = working["ward"].fillna(working["Địa chỉ"].apply(_extract_ward_from_address))
    if "Pháp lý" in working.columns:
        working["Pháp lý"] = working["Pháp lý"].apply(normalize_legal_status_for_ml)

    discarded_frames: list[pd.DataFrame] = []
    has_stated_district = working["district_stated_normalized"].notna()
    discarded_frames.append(
        _mark_discard_reason(
            working.loc[~has_stated_district],
            "missing_stated_district",
        )
    )
    valid_district_mask = has_stated_district & working["district_for_ml"].notna()
    discarded_frames.append(
        _mark_discard_reason(
            working.loc[has_stated_district & ~valid_district_mask],
            "district_not_in_allowed_hanoi_list",
        )
    )
    kept = working.loc[valid_district_mask].copy()

    kept["Latitude"] = pd.to_numeric(kept["Latitude"], errors="coerce")
    kept["Longitude"] = pd.to_numeric(kept["Longitude"], errors="coerce")
    has_coordinates = kept["Latitude"].notna() & kept["Longitude"].notna()
    if keep_missing_coordinates:
        no_coordinate_rows = kept.loc[~has_coordinates].copy()
        kept = kept.loc[has_coordinates].copy()
    else:
        discarded_frames.append(
            _mark_discard_reason(
                kept.loc[~has_coordinates],
                "missing_coordinates",
            )
        )
        no_coordinate_rows = pd.DataFrame(columns=kept.columns)
        kept = kept.loc[has_coordinates].copy()

    if not kept.empty:
        kept = _attach_district_geometry_validation(
            kept,
            mismatch_threshold_meters=mismatch_threshold_meters,
            snap_to_stated_district=snap_to_stated_district,
        )
        too_far_mask = kept["district_coordinate_distance_m"] > mismatch_threshold_meters
        discarded_frames.append(
            _mark_discard_reason(
                kept.loc[too_far_mask],
                "coordinate_more_than_threshold_from_stated_district",
            )
        )
        kept = kept.loc[~too_far_mask].copy()
    else:
        kept = _ensure_validation_columns(kept)

    if not no_coordinate_rows.empty:
        no_coordinate_rows = _ensure_validation_columns(no_coordinate_rows)
        kept = pd.concat([kept, no_coordinate_rows], ignore_index=True)

    kept = _finalize_cleaned_columns(kept)
    discarded = _combine_discarded(discarded_frames)
    summary = _build_summary(working, kept, discarded)
    return MLDatasetBuildResult(kept, discarded, summary)


def write_ml_dataset_outputs(
    result: MLDatasetBuildResult,
    *,
    output_path: Path,
    discarded_path: Path | None = None,
    summary_path: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.cleaned.to_csv(output_path, index=False, encoding="utf-8-sig")

    if discarded_path is not None:
        discarded_path.parent.mkdir(parents=True, exist_ok=True)
        result.discarded.to_csv(discarded_path, index=False, encoding="utf-8-sig")

    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        result.summary.to_csv(summary_path, index=False, encoding="utf-8-sig")


def _attach_district_geometry_validation(
    df: pd.DataFrame,
    *,
    mismatch_threshold_meters: float,
    snap_to_stated_district: bool,
) -> pd.DataFrame:
    districts = load_hanoi_districts()[["district_name", "district_name_normalized", "geometry"]].copy()
    if districts.empty:
        raise RuntimeError(
            "Hanoi district polygons are missing. Build or provide data/gis/hanoi_districts.geojson first."
        )

    districts_metric = districts.to_crs(METRIC_CRS)
    districts_by_normalized_name = districts_metric.set_index("district_name_normalized", drop=False)
    listings = gpd.GeoDataFrame(
        df.copy(),
        geometry=gpd.points_from_xy(df["Longitude"], df["Latitude"], crs=WGS84_CRS),
        crs=WGS84_CRS,
    ).to_crs(METRIC_CRS)

    joined = gpd.sjoin(
        listings,
        districts_metric[["district_name", "district_name_normalized", "geometry"]],
        how="left",
        predicate="within",
    )
    joined = joined.rename(
        columns={
            "district_name": "district_actual",
            "district_name_normalized": "district_actual_normalized",
        }
    )
    joined["district_match"] = (
        joined["district_actual_normalized"].notna()
        & (joined["district_actual_normalized"] == joined["district_stated_normalized"])
    )

    validation_rows: list[dict[str, Any]] = []
    for index, row in joined.iterrows():
        point = row.geometry
        stated_key = row["district_stated_normalized"]
        stated_district = districts_by_normalized_name.loc[stated_key]
        distance_m = 0.0 if stated_district.geometry.covers(point) else float(point.distance(stated_district.geometry))
        snapped_point = point
        snapped = False
        if (
            snap_to_stated_district
            and distance_m > 0
            and distance_m <= mismatch_threshold_meters
        ):
            snapped_point = nearest_points(point, stated_district.geometry)[1]
            snapped = True

        validation_rows.append(
            {
                "_row_index": index,
                "district_actual": row.get("district_actual"),
                "district_actual_normalized": row.get("district_actual_normalized"),
                "district_match": bool(row["district_match"]),
                "district_coordinate_distance_m": distance_m,
                "coordinate_snapped_to_stated_district": snapped,
                "geometry": snapped_point,
            }
        )

    validation = gpd.GeoDataFrame(validation_rows, geometry="geometry", crs=METRIC_CRS).set_index("_row_index")
    updated = listings.drop(columns=["geometry"]).join(validation.drop(columns=["geometry"]))
    snapped_wgs84 = validation.to_crs(WGS84_CRS)
    updated["Latitude_original"] = updated["Latitude"]
    updated["Longitude_original"] = updated["Longitude"]
    updated["Latitude"] = snapped_wgs84.geometry.y
    updated["Longitude"] = snapped_wgs84.geometry.x
    updated["district_mismatch_within_threshold"] = (
        ~updated["district_match"].fillna(False)
        & (updated["district_coordinate_distance_m"] <= mismatch_threshold_meters)
    )
    return pd.DataFrame(updated).reset_index(drop=True)


def _finalize_cleaned_columns(df: pd.DataFrame) -> pd.DataFrame:
    working = _ensure_validation_columns(df.copy())
    working["Huyện"] = working["district_for_ml"]
    working["dist_to_HN_center"] = working.apply(
        lambda row: haversine_km(row["Latitude"], row["Longitude"], THAP_RUA_LAT, THAP_RUA_LON),
        axis=1,
    )
    working["direction_to_HN_center"] = working.apply(
        lambda row: bearing_to_direction(
            bearing_degrees(row["Latitude"], row["Longitude"], THAP_RUA_LAT, THAP_RUA_LON)
        ),
        axis=1,
    )
    preferred_columns = [
        "Mã tin",
        "Link",
        "Tiêu đề",
        "Địa chỉ",
        "Huyện",
        "district_stated",
        "district_for_ml",
        "district_actual",
        "district_match",
        "district_mismatch_within_threshold",
        "district_coordinate_distance_m",
        "coordinate_snapped_to_stated_district",
        "ward",
        "Latitude",
        "Longitude",
        "Latitude_original",
        "Longitude_original",
        "Mức giá trị",
        "Giá/m² trị",
        "Diện tích trị",
        "Số phòng ngủ",
        "Mặt tiền",
        "Đường vào",
        "Số tầng",
        "Số toilet",
        "Pháp lý",
        "Loại tin",
        "Ngày đăng",
        "Ngày hết hạn",
        "dist_to_HN_center",
        "direction_to_HN_center",
    ]
    existing_preferred = [column for column in preferred_columns if column in working.columns]
    remaining = [column for column in working.columns if column not in existing_preferred]
    return working[existing_preferred + remaining].reset_index(drop=True)


def _ensure_validation_columns(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    defaults: dict[str, Any] = {
        "district_actual": pd.NA,
        "district_actual_normalized": pd.NA,
        "district_match": pd.NA,
        "district_coordinate_distance_m": pd.NA,
        "coordinate_snapped_to_stated_district": False,
        "Latitude_original": working.get("Latitude"),
        "Longitude_original": working.get("Longitude"),
        "district_mismatch_within_threshold": pd.NA,
    }
    for column, default in defaults.items():
        if column not in working.columns:
            working[column] = default
    return working


def _ensure_required_columns(df: pd.DataFrame) -> None:
    required = ["Huyện", "Latitude", "Longitude"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for ML dataset cleaning: {', '.join(missing)}")


def _normalize_ward_value(value: Any) -> str | pd.NA:
    text = clean_text(value)
    if text is None:
        return pd.NA
    return text


def normalize_legal_status_for_ml(value: Any) -> str | pd.NA:
    text = clean_text(value)
    if text is None:
        return pd.NA

    lowered = text.casefold()
    if any(token in lowered for token in ["hợp đồng", "hop dong", "chưa sổ", "chua so", "chờ sổ", "cho so"]):
        return "Chưa sổ"
    if "đang chờ" in lowered or "dang cho" in lowered:
        return "Chưa sổ"
    if any(token in lowered for token in ["sổ", "so", "sổ đỏ", "sổ hồng", "co so", "có sổ"]):
        return "Sổ đỏ/Sổ hồng"
    return pd.NA


def _extract_ward_from_address(value: Any) -> str | pd.NA:
    text = clean_text(value)
    if text is None:
        return pd.NA

    match = __import__("re").search(
        r"((?:phường|xã|thị trấn)\s+[^,;|()]+)",
        text,
        flags=__import__("re").IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return pd.NA


def _allowed_district_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for district in HANOI_DISTRICTS:
        normalized = normalize_district_name(district)
        if normalized:
            lookup[normalized] = district
    return lookup


def _mark_discard_reason(df: pd.DataFrame, reason: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    discarded = df.copy()
    discarded["discard_reason"] = reason
    return discarded


def _combine_discarded(frames: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return pd.DataFrame(columns=["discard_reason"])
    return pd.concat(non_empty, ignore_index=True)


def _build_summary(raw: pd.DataFrame, cleaned: pd.DataFrame, discarded: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "input_rows", "value": len(raw)},
        {"metric": "cleaned_rows", "value": len(cleaned)},
        {"metric": "discarded_rows", "value": len(discarded)},
    ]
    if not cleaned.empty and "coordinate_snapped_to_stated_district" in cleaned.columns:
        rows.append(
            {
                "metric": "snapped_coordinate_rows",
                "value": int(cleaned["coordinate_snapped_to_stated_district"].fillna(False).sum()),
            }
        )
    if not discarded.empty and "discard_reason" in discarded.columns:
        for reason, count in discarded["discard_reason"].value_counts(dropna=False).items():
            rows.append({"metric": f"discarded_{reason}", "value": int(count)})
    return pd.DataFrame(rows)
