from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd

from hanoi_real_estate.features.accessibility_sources import (
    ACCESSIBILITY_LAYER_FILES,
    WGS84_CRS,
)


METRIC_CRS = "EPSG:3857"
DEFAULT_WALK_RADIUS_M = 1000.0

FEATURE_PREFIX_BY_LAYER = {
    "universities": "university",
    "high_schools": "high_school",
    "hospitals": "hospital",
    "metro_stations": "metro_station",
    "bus_stops": "bus_stop",
    "major_roads": "major_road",
    "ring_roads": "ring_road",
}


@dataclass(frozen=True)
class AccessibilityFeatureSummary:
    layer: str
    feature_prefix: str
    poi_count: int
    rows_with_distance: int
    mean_distance_m: float | None
    rows_with_pois_in_radius: int


@dataclass(frozen=True)
class AccessibilityFeatureResult:
    data: pd.DataFrame
    summary: pd.DataFrame


def build_accessibility_feature_dataframe(
    listings_df: pd.DataFrame,
    *,
    layers: list[str] | None = None,
    walk_radius_m: float = DEFAULT_WALK_RADIUS_M,
) -> AccessibilityFeatureResult:
    """Add nearest-distance and radius-count accessibility features to listings."""
    working = listings_df.copy()
    _ensure_listing_coordinate_columns(working)
    if "ward" not in working.columns:
        working["ward"] = pd.NA
    requested_layers = layers or list(ACCESSIBILITY_LAYER_FILES)
    _validate_layers(requested_layers)

    listings_gdf = _build_listing_points(working)
    summary_rows: list[AccessibilityFeatureSummary] = []
    for layer in requested_layers:
        pois = load_accessibility_layer(layer)
        prefix = FEATURE_PREFIX_BY_LAYER[layer]
        distance_column = f"dist_nearest_{prefix}_m"
        count_column = f"{prefix}_count_{int(walk_radius_m)}m"

        if pois.empty or listings_gdf.empty:
            working[distance_column] = pd.NA
            working[count_column] = 0
            summary_rows.append(
                AccessibilityFeatureSummary(
                    layer=layer,
                    feature_prefix=prefix,
                    poi_count=len(pois),
                    rows_with_distance=0,
                    mean_distance_m=None,
                    rows_with_pois_in_radius=0,
                )
            )
            continue

        distances = _nearest_distances_m(listings_gdf, pois)
        counts = _counts_within_radius(listings_gdf, pois, radius_m=walk_radius_m)
        working[distance_column] = distances
        working[count_column] = counts

        distance_series = pd.Series(distances)
        count_series = pd.Series(counts)
        summary_rows.append(
            AccessibilityFeatureSummary(
                layer=layer,
                feature_prefix=prefix,
                poi_count=len(pois),
                rows_with_distance=int(distance_series.notna().sum()),
                mean_distance_m=float(distance_series.dropna().mean()) if distance_series.notna().any() else None,
                rows_with_pois_in_radius=int((count_series > 0).sum()),
            )
        )

    return AccessibilityFeatureResult(
        data=working,
        summary=pd.DataFrame([row.__dict__ for row in summary_rows]),
    )


def load_accessibility_layer(layer: str) -> gpd.GeoDataFrame:
    _validate_layers([layer])
    path = ACCESSIBILITY_LAYER_FILES[layer]
    if not path.exists():
        raise FileNotFoundError(
            f"Missing accessibility cache for {layer}: {path}. "
            "Run scripts/build_accessibility_gis_cache.py first."
        )
    frame = gpd.read_file(path)
    if frame.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=WGS84_CRS)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs or WGS84_CRS).to_crs(WGS84_CRS)


def write_accessibility_feature_outputs(
    result: AccessibilityFeatureResult,
    *,
    output_path: Path,
    summary_path: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.data.to_csv(output_path, index=False, encoding="utf-8-sig")
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        result.summary.to_csv(summary_path, index=False, encoding="utf-8-sig")


def _build_listing_points(listings_df: pd.DataFrame) -> gpd.GeoDataFrame:
    frame = listings_df.copy()
    frame["Latitude"] = pd.to_numeric(frame["Latitude"], errors="coerce")
    frame["Longitude"] = pd.to_numeric(frame["Longitude"], errors="coerce")
    valid = frame["Latitude"].notna() & frame["Longitude"].notna()
    frame = frame.loc[valid].copy()
    if frame.empty:
        return gpd.GeoDataFrame(frame, geometry=[], crs=WGS84_CRS)
    return gpd.GeoDataFrame(
        frame,
        geometry=gpd.points_from_xy(frame["Longitude"], frame["Latitude"], crs=WGS84_CRS),
        crs=WGS84_CRS,
    )


def _nearest_distances_m(listings_gdf: gpd.GeoDataFrame, pois: gpd.GeoDataFrame) -> pd.Series:
    left = listings_gdf.to_crs(METRIC_CRS)
    right = pois.to_crs(METRIC_CRS)
    joined = gpd.sjoin_nearest(
        left[["geometry"]],
        right[["geometry"]],
        how="left",
        distance_col="_distance_m",
    )
    distances = joined.groupby(joined.index)["_distance_m"].min()
    return distances.reindex(listings_gdf.index)


def _counts_within_radius(
    listings_gdf: gpd.GeoDataFrame,
    pois: gpd.GeoDataFrame,
    *,
    radius_m: float,
) -> pd.Series:
    left = listings_gdf.to_crs(METRIC_CRS)
    right = pois.to_crs(METRIC_CRS)
    buffers = left[["geometry"]].copy()
    buffers["geometry"] = buffers.geometry.buffer(radius_m)
    joined = gpd.sjoin(
        buffers,
        right[["geometry"]],
        how="left",
        predicate="intersects",
    )
    counts = joined.loc[joined["index_right"].notna()].groupby(level=0)["index_right"].nunique()
    return counts.reindex(listings_gdf.index, fill_value=0).astype(int)


def _ensure_listing_coordinate_columns(df: pd.DataFrame) -> None:
    missing = [column for column in ["Latitude", "Longitude"] if column not in df.columns]
    if missing:
        raise ValueError(f"Missing coordinate columns: {', '.join(missing)}")


def _validate_layers(layers: list[str]) -> None:
    unknown = sorted(set(layers) - set(ACCESSIBILITY_LAYER_FILES))
    if unknown:
        raise ValueError(f"Unknown accessibility layer(s): {', '.join(unknown)}")
