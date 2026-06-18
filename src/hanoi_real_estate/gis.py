from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from .analytics import THAP_RUA_LAT, THAP_RUA_LON, ensure_dashboard_dataframe, load_dashboard_dataframe
from .config import GIS_DATA_DIR
from .db import ensure_postgres_gis_cache_tables, fetch_all_rows, is_postgres_backend
from .repository import (
    fetch_cached_gis_district_choropleth,
    fetch_cached_gis_district_price,
    fetch_cached_gis_price_surface,
    replace_gis_district_choropleth,
    replace_gis_district_price,
    replace_gis_price_surface,
)


HANOI_BOUNDARY_PATH = GIS_DATA_DIR / "hanoi_boundary.geojson"
HANOI_DISTRICTS_PATH = GIS_DATA_DIR / "hanoi_districts.geojson"
DEFAULT_NETWORK_TYPE = "drive"


def ensure_gis_data_dir() -> Path:
    GIS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return GIS_DATA_DIR


def load_hanoi_boundary(force_refresh: bool = False) -> gpd.GeoDataFrame:
    ensure_gis_data_dir()
    if not force_refresh and HANOI_BOUNDARY_PATH.exists():
        return gpd.read_file(HANOI_BOUNDARY_PATH)

    ox = _import_osmnx()
    boundary = ox.geocode_to_gdf("Hanoi, Vietnam")
    boundary = boundary.to_crs(epsg=4326)
    boundary.to_file(HANOI_BOUNDARY_PATH, driver="GeoJSON")
    return boundary


def load_hanoi_boundary_geojson(force_refresh: bool = False) -> dict[str, Any]:
    boundary = load_hanoi_boundary(force_refresh=force_refresh)
    return json.loads(boundary.to_json())


def load_hanoi_districts(
    force_refresh: bool = False,
    allow_remote_fetch: bool = False,
) -> gpd.GeoDataFrame:
    ensure_gis_data_dir()
    if not force_refresh and HANOI_DISTRICTS_PATH.exists():
        districts = gpd.read_file(HANOI_DISTRICTS_PATH)
        return _prepare_districts_dataframe(districts)

    if not allow_remote_fetch and not force_refresh:
        return gpd.GeoDataFrame(
            columns=["district_name", "district_name_normalized", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    districts = _geocode_hanoi_districts()
    if districts.empty and HANOI_DISTRICTS_PATH.exists():
        return _prepare_districts_dataframe(gpd.read_file(HANOI_DISTRICTS_PATH))
    districts = _prepare_districts_dataframe(districts)
    if not districts.empty:
        districts.to_file(HANOI_DISTRICTS_PATH, driver="GeoJSON")
    return districts


def load_hanoi_districts_geojson(
    force_refresh: bool = False,
    allow_remote_fetch: bool = False,
) -> dict[str, Any]:
    districts = load_hanoi_districts(
        force_refresh=force_refresh,
        allow_remote_fetch=allow_remote_fetch,
    )
    if districts.empty:
        return {"type": "FeatureCollection", "features": []}
    return json.loads(districts.to_json())


def build_listing_geodataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> gpd.GeoDataFrame:
    df = ensure_dashboard_dataframe(df, active_only=active_only)
    if df.empty:
        return gpd.GeoDataFrame(df.copy(), geometry=[], crs="EPSG:4326")

    points = df.dropna(subset=["Latitude", "Longitude"]).copy()
    if points.empty:
        return gpd.GeoDataFrame(points, geometry=[], crs="EPSG:4326")

    geometry = gpd.points_from_xy(points["Longitude"], points["Latitude"], crs="EPSG:4326")
    return gpd.GeoDataFrame(points, geometry=geometry, crs="EPSG:4326")


def build_boundary_validation_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    listings_gdf = build_listing_geodataframe(df, active_only=active_only)
    if listings_gdf.empty:
        return pd.DataFrame(
            columns=[
                "Mã tin",
                "Tiêu đề",
                "Địa chỉ",
                "Huyện",
                "Latitude",
                "Longitude",
                "inside_hanoi",
                "boundary_name",
            ]
        )

    boundary = load_hanoi_boundary()[["display_name", "geometry"]].copy()
    joined = gpd.sjoin(listings_gdf, boundary, how="left", predicate="within")
    joined["inside_hanoi"] = joined["display_name"].notna()
    joined = joined.rename(columns={"display_name": "boundary_name"})

    columns = [
        "Mã tin",
        "Tiêu đề",
        "Địa chỉ",
        "Huyện",
        "Latitude",
        "Longitude",
        "inside_hanoi",
        "boundary_name",
    ]
    return pd.DataFrame(joined[columns]).reset_index(drop=True)


def build_district_validation_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    listings_gdf = build_listing_geodataframe(df, active_only=active_only)
    if listings_gdf.empty:
        return pd.DataFrame(
            columns=[
                "Mã tin",
                "Tiêu đề",
                "Địa chỉ",
                "Huyện",
                "Latitude",
                "Longitude",
                "district_osm",
                "district_name_normalized",
                "district_text_normalized",
                "district_match",
            ]
        )

    districts = load_hanoi_districts()[["district_name", "district_name_normalized", "geometry"]].copy()
    if districts.empty:
        empty = listings_gdf.copy()
        empty["district_osm"] = pd.NA
        empty["district_name_normalized"] = pd.NA
        empty["district_text_normalized"] = empty["Huyện"].apply(normalize_district_name)
        empty["district_match"] = pd.NA
        return pd.DataFrame(
            empty[
                [
                    "Mã tin",
                    "Tiêu đề",
                    "Địa chỉ",
                    "Huyện",
                    "Latitude",
                    "Longitude",
                    "district_osm",
                    "district_name_normalized",
                    "district_text_normalized",
                    "district_match",
                ]
            ]
        ).reset_index(drop=True)

    joined = gpd.sjoin(listings_gdf, districts, how="left", predicate="within")
    joined["district_text_normalized"] = joined["Huyện"].apply(normalize_district_name)
    joined["district_match"] = (
        joined["district_name_normalized"].notna()
        & joined["district_text_normalized"].notna()
        & (joined["district_name_normalized"] == joined["district_text_normalized"])
    )
    joined = joined.rename(columns={"district_name": "district_osm"})

    columns = [
        "Mã tin",
        "Tiêu đề",
        "Địa chỉ",
        "Huyện",
        "Latitude",
        "Longitude",
        "district_osm",
        "district_name_normalized",
        "district_text_normalized",
        "district_match",
    ]
    return pd.DataFrame(joined[columns]).reset_index(drop=True)


def build_pydeck_point_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    gdf = build_listing_geodataframe(df, active_only=active_only)
    if gdf.empty:
        return pd.DataFrame(
            columns=[
                "Mã tin",
                "Tiêu đề",
                "Địa chỉ",
                "Latitude",
                "Longitude",
                "Giá/m² trị",
                "Mức giá trị",
                "heatmap_weight",
            ]
        )

    frame = pd.DataFrame(gdf.drop(columns="geometry")).copy()
    frame["Giá/m² trị"] = pd.to_numeric(frame["Giá/m² trị"], errors="coerce")
    frame["Mức giá trị"] = pd.to_numeric(frame["Mức giá trị"], errors="coerce")
    frame["tooltip_price_per_m2"] = frame["Giá/m²"].fillna("N/A")
    frame["tooltip_total_price"] = frame["Mức giá"].fillna("N/A")
    frame["heatmap_weight"] = frame["Giá/m² trị"].fillna(0)
    return frame.reset_index(drop=True)


def build_price_hexbin_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    frame = build_pydeck_point_dataframe(df, active_only=active_only)
    if frame.empty:
        frame = frame.copy()
        frame["Giá/m² clipped"] = pd.Series(dtype="float64")
        return frame
    frame = frame.dropna(subset=["Latitude", "Longitude", "Giá/m² trị"]).copy()
    frame = frame[frame["Giá/m² trị"] > 0].copy()
    if frame.empty:
        frame["Giá/m² clipped"] = pd.Series(dtype="float64")
        return frame.reset_index(drop=True)

    lower_bound = frame["Giá/m² trị"].quantile(0.01)
    upper_bound = frame["Giá/m² trị"].quantile(0.99)
    frame["Giá/m² clipped"] = frame["Giá/m² trị"].clip(lower=lower_bound, upper=upper_bound)
    return frame.reset_index(drop=True)


def build_district_price_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    columns = [
        "district_osm",
        "district_name_normalized",
        "avg_price_per_m2",
        "listing_count",
    ]
    listings_gdf = build_listing_geodataframe(df, active_only=active_only)
    if listings_gdf.empty:
        return pd.DataFrame(columns=columns)

    price_points = listings_gdf.copy()
    price_points["Giá/m² trị"] = pd.to_numeric(price_points["Giá/m² trị"], errors="coerce")
    price_points = price_points.dropna(subset=["Giá/m² trị"]).copy()
    price_points = price_points[price_points["Giá/m² trị"] > 0].copy()
    if price_points.empty:
        return pd.DataFrame(columns=columns)

    districts = load_hanoi_districts()[["district_name", "district_name_normalized", "geometry"]].copy()
    if districts.empty:
        return pd.DataFrame(columns=columns)

    joined = gpd.sjoin(price_points, districts, how="inner", predicate="within")
    if joined.empty:
        return pd.DataFrame(columns=columns)

    grouped = (
        joined.groupby(["district_name", "district_name_normalized"], dropna=False)
        .agg(
            avg_price_per_m2=("Giá/m² trị", "mean"),
            listing_count=("Mã tin", "count"),
        )
        .reset_index()
        .rename(columns={"district_name": "district_osm"})
        .sort_values(
            by=["avg_price_per_m2", "listing_count"],
            ascending=[False, False],
        )
        .reset_index(drop=True)
    )
    return grouped[columns]


def build_interpolated_price_surface_dataframe(
    df: pd.DataFrame | None = None,
    *,
    active_only: bool = True,
    cell_size_meters: float = 400.0,
    k_neighbors: int = 10,
    power: float = 2.0,
    max_distance_meters: float = 12000.0,
) -> pd.DataFrame:
    points = build_price_hexbin_dataframe(df, active_only=active_only)
    if points.empty:
        return pd.DataFrame(
            columns=[
                "Longitude",
                "Latitude",
                "predicted_price_per_m2",
                "cell_polygon",
            ]
        )

    boundary = load_hanoi_boundary()
    boundary_metric = boundary.to_crs(epsg=3857)
    minx, miny, maxx, maxy = boundary_metric.total_bounds

    xs = np.arange(minx, maxx, cell_size_meters)
    ys = np.arange(miny, maxy, cell_size_meters)
    if len(xs) < 2 or len(ys) < 2:
        return pd.DataFrame(
            columns=[
                "Longitude",
                "Latitude",
                "predicted_price_per_m2",
                "cell_polygon",
            ]
        )

    point_gdf = gpd.GeoDataFrame(
        points.copy(),
        geometry=gpd.points_from_xy(points["Longitude"], points["Latitude"], crs="EPSG:4326"),
        crs="EPSG:4326",
    ).to_crs(epsg=3857)
    point_coords = np.column_stack((point_gdf.geometry.x.to_numpy(), point_gdf.geometry.y.to_numpy()))
    point_values = point_gdf["Giá/m² trị"].to_numpy(dtype=float)

    rows: list[dict[str, Any]] = []
    for x in xs:
        for y in ys:
            center_x = x + (cell_size_meters / 2)
            center_y = y + (cell_size_meters / 2)
            center_geom = Point(center_x, center_y)
            if not boundary_metric.geometry.iloc[0].contains(center_geom):
                continue

            distances = np.sqrt(((point_coords - np.array([center_x, center_y])) ** 2).sum(axis=1))
            nearest_count = min(k_neighbors, len(distances))
            nearest_idx = np.argpartition(distances, nearest_count - 1)[:nearest_count]
            nearest_distances = distances[nearest_idx]
            nearest_values = point_values[nearest_idx]
            within_range = nearest_distances <= max_distance_meters
            if not within_range.any():
                continue
            nearest_distances = nearest_distances[within_range]
            nearest_values = nearest_values[within_range]

            weights = 1.0 / np.maximum(nearest_distances, 1.0) ** power
            predicted_value = float(np.average(nearest_values, weights=weights))

            min_lon = center_x - (cell_size_meters / 2)
            max_lon = center_x + (cell_size_meters / 2)
            min_lat = center_y - (cell_size_meters / 2)
            max_lat = center_y + (cell_size_meters / 2)
            polygon_coords = [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]

            rows.append(
                {
                    "Longitude": center_x,
                    "Latitude": center_y,
                    "predicted_price_per_m2": predicted_value,
                    "cell_polygon": polygon_coords,
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "Longitude",
                "Latitude",
                "predicted_price_per_m2",
                "cell_polygon",
            ]
        )

    surface_df = pd.DataFrame(rows)
    centers = gpd.GeoDataFrame(
        surface_df,
        geometry=gpd.points_from_xy(surface_df["Longitude"], surface_df["Latitude"], crs="EPSG:3857"),
        crs="EPSG:3857",
    ).to_crs(epsg=4326)
    surface_df["Longitude"] = centers.geometry.x
    surface_df["Latitude"] = centers.geometry.y

    converted_polygons: list[list[list[float]]] = []
    for polygon in surface_df["cell_polygon"]:
        ring_df = pd.DataFrame(polygon, columns=["x", "y"])
        ring_gdf = gpd.GeoDataFrame(
            ring_df,
            geometry=gpd.points_from_xy(ring_df["x"], ring_df["y"], crs="EPSG:3857"),
            crs="EPSG:3857",
        ).to_crs(epsg=4326)
        converted_polygons.append(
            [[float(point.x), float(point.y)] for point in ring_gdf.geometry]
        )
    surface_df["cell_polygon"] = converted_polygons
    return surface_df.reset_index(drop=True)


def refresh_cached_gis_layers(active_only: bool = True) -> dict[str, int]:
    if not is_postgres_backend():
        raise RuntimeError("Cached GIS layers require PostgreSQL.")

    ensure_postgres_gis_cache_tables()
    base_df = load_dashboard_dataframe(active_only=active_only)
    district_df = build_district_price_dataframe(base_df, active_only=active_only)
    surface_df = build_interpolated_price_surface_dataframe(base_df, active_only=active_only)
    district_geojson = build_district_price_geojson(
        load_hanoi_districts_geojson(),
        district_df,
    )

    district_rows = replace_gis_district_price(district_df.to_dict(orient="records"))
    surface_rows = replace_gis_price_surface(surface_df.to_dict(orient="records"))
    replace_gis_district_choropleth(district_geojson)
    return {
        "district_rows": district_rows,
        "surface_rows": surface_rows,
    }


def load_cached_gis_price_surface_dataframe() -> pd.DataFrame:
    if is_postgres_backend():
        ensure_postgres_gis_cache_tables()
    rows = fetch_cached_gis_price_surface()
    if not rows:
        return pd.DataFrame(
            columns=[
                "Longitude",
                "Latitude",
                "predicted_price_per_m2",
                "cell_polygon",
            ]
        )

    frame = pd.DataFrame(rows).rename(
        columns={
            "longitude": "Longitude",
            "latitude": "Latitude",
        }
    )
    frame["Longitude"] = pd.to_numeric(frame["Longitude"], errors="coerce")
    frame["Latitude"] = pd.to_numeric(frame["Latitude"], errors="coerce")
    frame["predicted_price_per_m2"] = pd.to_numeric(frame["predicted_price_per_m2"], errors="coerce")
    frame["cell_polygon"] = frame["cell_polygon"].apply(_deserialize_cell_polygon)
    return frame[["Longitude", "Latitude", "predicted_price_per_m2", "cell_polygon"]].reset_index(drop=True)


def load_cached_gis_district_price_dataframe() -> pd.DataFrame:
    if is_postgres_backend():
        ensure_postgres_gis_cache_tables()
    rows = fetch_cached_gis_district_price()
    if not rows:
        return pd.DataFrame(
            columns=[
                "district_osm",
                "district_name_normalized",
                "avg_price_per_m2",
                "listing_count",
            ]
        )

    frame = pd.DataFrame(rows)
    frame["avg_price_per_m2"] = pd.to_numeric(frame["avg_price_per_m2"], errors="coerce")
    frame["listing_count"] = pd.to_numeric(frame["listing_count"], errors="coerce").fillna(0).astype(int)
    return frame[
        [
            "district_osm",
            "district_name_normalized",
            "avg_price_per_m2",
            "listing_count",
        ]
    ].reset_index(drop=True)


def load_cached_gis_district_choropleth() -> dict[str, Any]:
    if is_postgres_backend():
        ensure_postgres_gis_cache_tables()
    payload = fetch_cached_gis_district_choropleth()
    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        return payload
    return {"type": "FeatureCollection", "features": []}


def get_hanoi_center_view_state() -> dict[str, float]:
    return {
        "latitude": THAP_RUA_LAT,
        "longitude": THAP_RUA_LON,
        "zoom": 10.2,
        "pitch": 0,
        "bearing": 0,
    }


def build_osmnx_graph(
    network_type: str = DEFAULT_NETWORK_TYPE,
    force_refresh: bool = False,
):
    ox = _import_osmnx()
    ensure_gis_data_dir()
    graph_path = GIS_DATA_DIR / f"hanoi_{network_type}.graphml"
    if graph_path.exists() and not force_refresh:
        return ox.load_graphml(graph_path)

    graph = ox.graph_from_place("Hanoi, Vietnam", network_type=network_type)
    graph = ox.routing.add_edge_speeds(graph)
    graph = ox.routing.add_edge_travel_times(graph)
    ox.save_graphml(graph, graph_path)
    return graph


def calculate_shortest_path_to_hoan_kiem(
    latitude: float,
    longitude: float,
    network_type: str = DEFAULT_NETWORK_TYPE,
) -> dict[str, Any]:
    ox = _import_osmnx()
    graph = build_osmnx_graph(network_type=network_type)
    origin_node = ox.distance.nearest_nodes(graph, X=longitude, Y=latitude)
    destination_node = ox.distance.nearest_nodes(graph, X=THAP_RUA_LON, Y=THAP_RUA_LAT)

    route = ox.routing.shortest_path(graph, origin_node, destination_node, weight="travel_time")
    if not route:
        return {
            "route": [],
            "distance_km": None,
            "travel_time_min": None,
        }

    route_gdf = ox.routing.route_to_gdf(graph, route)
    edge_lengths_m = route_gdf["length"].sum()
    edge_travel_time_s = route_gdf["travel_time"].sum()
    route_points = [
        {"lat": float(graph.nodes[node]["y"]), "lon": float(graph.nodes[node]["x"])}
        for node in route
    ]
    return {
        "route": route_points,
        "distance_km": float(edge_lengths_m) / 1000.0,
        "travel_time_min": float(edge_travel_time_s) / 60.0,
    }


def normalize_district_name(value: Any) -> str | None:
    if pd.isna(value) or value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    text = text.casefold()
    text = re.sub(r"^(quan|quận|huyen|huyện|thi xa|thị xã|thanh pho|thành phố)\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _prepare_districts_dataframe(districts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    working = districts.copy()
    for column in [
        "name:vi",
        "name",
        "alt_name",
        "official_name",
        "district_name",
        "NAME_2",
        "VARNAME_2",
    ]:
        if column not in working.columns:
            working[column] = None

    working["district_name"] = (
        working["district_name"]
        .fillna(working["name:vi"])
        .fillna(working["name"])
        .fillna(working["alt_name"])
        .fillna(working["official_name"])
        .fillna(working["NAME_2"])
        .fillna(working["VARNAME_2"])
    )
    working["district_name_normalized"] = working["district_name"].apply(normalize_district_name)
    working = working[working.geometry.notna()].copy()
    working = working[working.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    working = working[working["district_name_normalized"].notna()].copy()
    working = working.drop_duplicates(subset=["district_name_normalized"]).copy()
    working = working.to_crs(epsg=4326)

    columns = [
        column
        for column in [
            "district_name",
            "district_name_normalized",
            "display_name",
            "geometry",
        ]
        if column in working.columns
    ]
    return working[columns].reset_index(drop=True)


def _geocode_hanoi_districts() -> gpd.GeoDataFrame:
    ox = _import_osmnx()
    rows: list[gpd.GeoDataFrame] = []
    for district_name in _fetch_known_hanoi_district_names():
        query = {"city": "Hà Nội", "country": "Việt Nam", "county": district_name}
        try:
            gdf = ox.geocode_to_gdf(query)
        except Exception:
            continue

        if gdf.empty:
            continue
        gdf = gdf[gdf.geometry.notna()].copy()
        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if gdf.empty:
            continue

        metric_gdf = gdf.to_crs(epsg=3857)
        area_km2 = metric_gdf.geometry.area / 1_000_000
        plausible = gdf.loc[area_km2 >= 5].copy()
        if plausible.empty:
            continue

        plausible["district_name"] = district_name
        rows.append(plausible.to_crs(epsg=4326))

    if not rows:
        return gpd.GeoDataFrame(columns=["district_name", "geometry"], geometry="geometry", crs="EPSG:4326")

    combined = pd.concat(rows, ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")


def _fetch_known_hanoi_district_names() -> list[str]:
    query = """
        SELECT DISTINCT district
        FROM address
        WHERE district IS NOT NULL
          AND TRIM(district) != ''
        ORDER BY district
    """
    rows = fetch_all_rows(query)
    return [str(row["district"]).strip() for row in rows if row["district"]]


def _deserialize_cell_polygon(value: Any) -> list[list[float]]:
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
        return []
    if isinstance(value, list):
        return value
    return []


def build_district_price_geojson(district_geojson: dict, district_price_df: pd.DataFrame) -> dict:
    if not district_geojson.get("features"):
        return {"type": "FeatureCollection", "features": []}

    lookup = {}
    if not district_price_df.empty:
        for _, row in district_price_df.iterrows():
            lookup[str(row["district_osm"])] = {
                "avg_price_per_m2": float(row["avg_price_per_m2"]),
                "listing_count": int(row["listing_count"]),
                "fill_color": _price_to_color(row["avg_price_per_m2"]),
            }

    features = []
    for feature in district_geojson.get("features", []):
        properties = dict(feature.get("properties", {}))
        district_name = str(properties.get("district_name") or properties.get("name") or "")
        stats = lookup.get(district_name)
        if stats:
            properties.update(stats)
        else:
            properties["avg_price_per_m2"] = None
            properties["listing_count"] = 0
            properties["fill_color"] = [220, 220, 220, 70]
        features.append(
            {
                "type": feature.get("type", "Feature"),
                "geometry": feature.get("geometry"),
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _price_to_color(value: float) -> list[int]:
    if pd.isna(value):
        return [220, 220, 220, 120]
    thresholds = [
        (25, [49, 54, 149, 185]),
        (75, [69, 117, 180, 185]),
        (150, [116, 173, 209, 185]),
        (250, [171, 217, 233, 185]),
        (350, [253, 174, 97, 195]),
        (999999, [240, 59, 32, 200]),
    ]
    numeric = float(value)
    for upper_bound, color in thresholds:
        if numeric <= upper_bound:
            return color
    return [240, 59, 32, 200]


def _import_osmnx():
    try:
        import osmnx as ox
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "osmnx is required for remote GIS graph/geocoding operations but is not installed in this environment."
        ) from exc
    return ox
