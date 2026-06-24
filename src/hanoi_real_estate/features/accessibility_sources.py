from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from hanoi_real_estate.config import GIS_DATA_DIR
from hanoi_real_estate.gis import load_hanoi_boundary


ACCESSIBILITY_DIR = GIS_DATA_DIR / "accessibility"
HANOI_PLACE_NAME = "Hanoi, Vietnam"
WGS84_CRS = "EPSG:4326"

ACCESSIBILITY_LAYER_FILES = {
    "universities": ACCESSIBILITY_DIR / "universities.geojson",
    "high_schools": ACCESSIBILITY_DIR / "high_schools.geojson",
    "hospitals": ACCESSIBILITY_DIR / "hospitals.geojson",
    "prisons": ACCESSIBILITY_DIR / "prisons.geojson",
    "metro_stations": ACCESSIBILITY_DIR / "metro_stations.geojson",
    "bus_stops": ACCESSIBILITY_DIR / "bus_stops.geojson",
    "major_roads": ACCESSIBILITY_DIR / "major_roads.geojson",
    "ring_roads": ACCESSIBILITY_DIR / "ring_roads.geojson",
}
ACCESSIBILITY_METADATA_PATH = ACCESSIBILITY_DIR / "metadata.json"

OSM_TAGS_BY_LAYER: dict[str, dict[str, Any]] = {
    "universities": {
        "amenity": ["university", "college"],
    },
    "high_schools": {
        "amenity": "school",
    },
    "hospitals": {
        "amenity": "hospital",
        "healthcare": "hospital",
    },
    "prisons": {
        "amenity": "prison",
        "building": "prison",
        "landuse": "military",
        "institution": "prison",
    },
    "metro_stations": {
        "railway": ["station", "subway_entrance"],
        "station": "subway",
        "public_transport": "station",
    },
    "bus_stops": {
        "highway": "bus_stop",
        "public_transport": ["platform", "stop_position", "station"],
        "bus": "yes",
    },
    "major_roads": {
        "highway": [
            "motorway",
            "motorway_link",
            "trunk",
            "trunk_link",
            "primary",
            "primary_link",
            "secondary",
            "secondary_link",
        ],
    },
}

SCALAR_COLUMNS = [
    "element_type",
    "osmid",
    "name",
    "name:vi",
    "alt_name",
    "official_name",
    "amenity",
    "healthcare",
    "building",
    "landuse",
    "institution",
    "highway",
    "railway",
    "station",
    "public_transport",
    "bus",
    "operator",
    "network",
    "ref",
    "route",
    "isced:level",
    "school:level",
    "grades",
    "addr:street",
    "addr:district",
    "geometry",
]


@dataclass(frozen=True)
class AccessibilityLayerResult:
    layer: str
    path: Path
    row_count: int
    source: str
    status: str


def build_accessibility_gis_cache(
    *,
    layers: list[str] | None = None,
    force_refresh: bool = False,
) -> list[AccessibilityLayerResult]:
    """Fetch and cache current Hanoi accessibility layers from OpenStreetMap."""
    ACCESSIBILITY_DIR.mkdir(parents=True, exist_ok=True)
    requested_layers = layers or list(ACCESSIBILITY_LAYER_FILES)
    _validate_layers(requested_layers)

    results: list[AccessibilityLayerResult] = []
    fetched_frames: dict[str, gpd.GeoDataFrame] = {}
    for layer in requested_layers:
        path = ACCESSIBILITY_LAYER_FILES[layer]
        if path.exists() and not force_refresh:
            cached = gpd.read_file(path)
            results.append(
                AccessibilityLayerResult(
                    layer=layer,
                    path=path,
                    row_count=len(cached),
                    source="cache",
                    status="kept_existing",
                )
            )
            fetched_frames[layer] = cached
            continue

        if layer == "ring_roads":
            major_roads = fetched_frames.get("major_roads")
            if major_roads is None:
                major_roads = _load_or_fetch_major_roads(force_refresh=force_refresh)
            frame = filter_ring_roads(major_roads)
        else:
            frame = fetch_osm_accessibility_layer(layer)

        frame = clean_accessibility_layer(frame, layer)
        frame.to_file(path, driver="GeoJSON")
        fetched_frames[layer] = frame
        results.append(
            AccessibilityLayerResult(
                layer=layer,
                path=path,
                row_count=len(frame),
                source="openstreetmap",
                status="refreshed",
            )
        )

    write_accessibility_metadata(results)
    return results


def fetch_osm_accessibility_layer(layer: str) -> gpd.GeoDataFrame:
    _validate_layers([layer])
    if layer == "ring_roads":
        raise ValueError("ring_roads is derived from major_roads; call build_accessibility_gis_cache instead.")

    ox = _import_osmnx()
    tags = OSM_TAGS_BY_LAYER[layer]
    frame = ox.features_from_place(HANOI_PLACE_NAME, tags=tags)
    if frame.empty:
        return _empty_layer()
    return _reset_osm_index(gpd.GeoDataFrame(frame, geometry="geometry", crs=WGS84_CRS))


def clean_accessibility_layer(frame: gpd.GeoDataFrame, layer: str) -> gpd.GeoDataFrame:
    if frame.empty:
        return _empty_layer()

    working = frame.copy()
    working = working[working.geometry.notna()].copy()
    if working.empty:
        return _empty_layer()

    working = working.to_crs(WGS84_CRS)
    working = _clip_to_hanoi_boundary(working)
    if layer == "high_schools":
        working = _filter_high_schools(working)
    elif layer == "prisons":
        working = _filter_prisons(working)
    elif layer == "metro_stations":
        working = _filter_metro_stations(working)
    elif layer == "bus_stops":
        working = _filter_bus_stops(working)
    elif layer == "major_roads":
        working = _filter_major_roads(working)
    elif layer == "ring_roads":
        working = filter_ring_roads(working)

    working = _dedupe_by_geometry_and_name(working)
    working["accessibility_layer"] = layer
    columns = [column for column in SCALAR_COLUMNS if column in working.columns]
    if "accessibility_layer" not in columns:
        columns.insert(0, "accessibility_layer")
    if "geometry" not in columns:
        columns.append("geometry")
    working = working[columns].copy()
    working = _coerce_geojson_safe_columns(working)
    return gpd.GeoDataFrame(working, geometry="geometry", crs=WGS84_CRS).reset_index(drop=True)


def filter_ring_roads(major_roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if major_roads.empty:
        return _empty_layer()

    working = major_roads.copy()
    text = _combined_text_series(working, ["name", "name:vi", "alt_name", "official_name", "ref"])
    ring_pattern = r"vành\s*đai|vanh\s*dai|ring\s*road|beltway|\brr\s*[0-9]"
    return working.loc[text.str.contains(ring_pattern, case=False, regex=True, na=False)].copy()


def _filter_prisons(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    text = _combined_text_series(
        frame,
        ["name", "name:vi", "alt_name", "official_name", "amenity", "building", "institution"],
    )
    prison_mask = (
        frame.get("amenity", pd.Series(index=frame.index, dtype="object")).astype(str).str.contains(
            "prison", case=False, na=False
        )
        | frame.get("building", pd.Series(index=frame.index, dtype="object")).astype(str).str.contains(
            "prison", case=False, na=False
        )
        | frame.get("institution", pd.Series(index=frame.index, dtype="object")).astype(str).str.contains(
            "prison", case=False, na=False
        )
        | text.str.contains(
            r"trại\s*tạm\s*giam|trai\s*tam\s*giam|trại\s*giam|trai\s*giam|nhà\s*tù|nha\s*tu|prison|detention",
            case=False,
            regex=True,
            na=False,
        )
    )
    return frame.loc[prison_mask].copy()


def write_accessibility_metadata(results: list[AccessibilityLayerResult]) -> None:
    ACCESSIBILITY_DIR.mkdir(parents=True, exist_ok=True)
    by_layer = {result.layer: result for result in results}
    layer_payloads = []
    for layer, path in ACCESSIBILITY_LAYER_FILES.items():
        result = by_layer.get(layer)
        if result is not None:
            layer_payloads.append(
                {
                    "layer": result.layer,
                    "path": str(result.path),
                    "row_count": result.row_count,
                    "source": result.source,
                    "status": result.status,
                }
            )
            continue
        if path.exists():
            layer_payloads.append(
                {
                    "layer": layer,
                    "path": str(path),
                    "row_count": len(gpd.read_file(path)),
                    "source": "cache",
                    "status": "existing_cache_not_touched",
                }
            )

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "place": HANOI_PLACE_NAME,
        "source": "OpenStreetMap via OSMnx/Overpass",
        "layers": layer_payloads,
    }
    ACCESSIBILITY_METADATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_or_fetch_major_roads(*, force_refresh: bool) -> gpd.GeoDataFrame:
    path = ACCESSIBILITY_LAYER_FILES["major_roads"]
    if path.exists() and not force_refresh:
        return gpd.read_file(path)
    frame = clean_accessibility_layer(fetch_osm_accessibility_layer("major_roads"), "major_roads")
    frame.to_file(path, driver="GeoJSON")
    return frame


def _reset_osm_index(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    working = frame.copy()
    index_names = list(working.index.names)
    working = working.reset_index()
    rename_map: dict[str, str] = {}
    if index_names and index_names[0] in working.columns:
        rename_map[index_names[0]] = "element_type"
    if len(index_names) > 1 and index_names[1] in working.columns:
        rename_map[index_names[1]] = "osmid"
    working = working.rename(columns=rename_map)
    return gpd.GeoDataFrame(working, geometry="geometry", crs=frame.crs or WGS84_CRS)


def _clip_to_hanoi_boundary(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    boundary = load_hanoi_boundary()
    if boundary.empty:
        return frame
    boundary = boundary.to_crs(frame.crs)
    return gpd.clip(frame, boundary[["geometry"]])


def _filter_high_schools(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    text = _combined_text_series(frame, ["name", "name:vi", "alt_name", "official_name", "school:level", "grades"])
    pattern = r"\bthpt\b|trung học phổ thông|trung hoc pho thong|high school|cấp\s*3|cap\s*3"
    filtered = frame.loc[text.str.contains(pattern, case=False, regex=True, na=False)].copy()
    if filtered.empty:
        return frame.iloc[0:0].copy()
    return filtered


def _filter_metro_stations(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    working = frame.copy()
    text = _combined_text_series(working, ["name", "name:vi", "alt_name", "official_name", "network", "operator"])
    metro_mask = (
        working.get("station", pd.Series(index=working.index, dtype="object")).astype(str).str.contains("subway", case=False, na=False)
        | working.get("railway", pd.Series(index=working.index, dtype="object")).astype(str).str.contains("station|subway_entrance", case=False, regex=True, na=False)
        | text.str.contains("metro|cát linh|cat linh|hà đông|ha dong|nhổn|nhon|đường sắt đô thị|duong sat do thi", case=False, regex=True, na=False)
    )
    return working.loc[metro_mask].copy()


def _filter_bus_stops(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    working = frame.copy()
    text = _combined_text_series(working, ["name", "name:vi", "alt_name", "official_name", "network", "operator", "route"])
    bus_mask = (
        working.get("highway", pd.Series(index=working.index, dtype="object")).astype(str).str.contains("bus_stop", case=False, na=False)
        | working.get("bus", pd.Series(index=working.index, dtype="object")).astype(str).str.contains("yes", case=False, na=False)
        | text.str.contains(r"\bbus\b|xe buýt|xe buyt", case=False, regex=True, na=False)
    )
    return working.loc[bus_mask].copy()


def _filter_major_roads(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    highway = frame.get("highway", pd.Series(index=frame.index, dtype="object")).apply(_stringify_value)
    pattern = r"motorway|trunk|primary|secondary"
    return frame.loc[highway.str.contains(pattern, case=False, regex=True, na=False)].copy()


def _dedupe_by_geometry_and_name(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if frame.empty:
        return frame

    working = frame.copy()
    name = _combined_text_series(working, ["name", "name:vi", "alt_name", "official_name"])
    working["_dedupe_name"] = name.str.casefold().str.strip()
    working["_dedupe_geometry"] = working.geometry.to_wkb(hex=True)
    working = working.drop_duplicates(subset=["_dedupe_name", "_dedupe_geometry"]).copy()
    return working.drop(columns=["_dedupe_name", "_dedupe_geometry"])


def _coerce_geojson_safe_columns(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    working = frame.copy()
    for column in working.columns:
        if column == "geometry":
            continue
        working[column] = working[column].apply(_stringify_value)
    return working


def _combined_text_series(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    text = pd.Series("", index=frame.index, dtype="object")
    for column in columns:
        if column in frame.columns:
            text = text + " " + frame[column].apply(_stringify_value)
    return text.str.strip()


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if pd.isna(value):
        return ""
    return str(value)


def _empty_layer() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns=["accessibility_layer", "geometry"], geometry="geometry", crs=WGS84_CRS)


def _validate_layers(layers: list[str]) -> None:
    unknown = sorted(set(layers) - set(ACCESSIBILITY_LAYER_FILES))
    if unknown:
        raise ValueError(f"Unknown accessibility layer(s): {', '.join(unknown)}")


def _import_osmnx():
    try:
        import osmnx as ox
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "osmnx is required for accessibility GIS cache building. Install requirements-worker.txt."
        ) from exc

    ox.settings.use_cache = True
    ox.settings.log_console = False
    ox.settings.requests_timeout = 180
    return ox
