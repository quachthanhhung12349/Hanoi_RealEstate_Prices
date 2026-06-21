from __future__ import annotations

import math
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import joblib
import pandas as pd
import folium
import requests
from streamlit_folium import st_folium

from hanoi_real_estate.analytics import THAP_RUA_LAT, THAP_RUA_LON, haversine_km
from hanoi_real_estate.config import DATA_DIR, ROOT_DIR
from hanoi_real_estate.gis import load_hanoi_districts, normalize_district_name
from hanoi_real_estate.features.accessibility_features import (
    FEATURE_PREFIX_BY_LAYER,
    METRIC_CRS,
    load_accessibility_layer,
)
from hanoi_real_estate.features.accessibility_sources import ACCESSIBILITY_LAYER_FILES
from hanoi_real_estate.features.ml_dataset import normalize_legal_status_for_ml
from hanoi_real_estate.parsers import clean_text
from hanoi_real_estate.ml.price_model import MODEL_FEATURES


MODEL_PATH_CANDIDATES = [
    ROOT_DIR / "models" / "xgboost_price_per_m2_pipeline.joblib",
    DATA_DIR / "ml" / "postgres_test" / "model" / "xgboost_price_per_m2_pipeline.joblib",
    DATA_DIR / "ml" / "model" / "xgboost_price_per_m2_pipeline.joblib",
]
WGS84_CRS = "EPSG:4326"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


@dataclass(frozen=True)
class PricePredictionInput:
    district: str
    ward: str
    latitude: float
    longitude: float
    area_m2: float
    bedrooms: str | None = None
    front_length_m: float | None = None
    road_size_m: float | None = None
    floors: float | None = None
    toilets: str | None = None
    legal_status: str | None = None


@dataclass(frozen=True)
class PricePredictionResult:
    price_per_m2_million_vnd: float
    total_price_billion_vnd: float
    features: pd.DataFrame
    model_path: Path


@dataclass(frozen=True)
class LocationOption:
    label: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class ResolvedAdminLocation:
    district: str | None
    ward: str | None
    district_source: str | None = None
    ward_source: str | None = None


def find_model_path() -> Path | None:
    for path in MODEL_PATH_CANDIDATES:
        if path.exists():
            return path
    return None


def load_price_model(model_path: Path | None = None):
    path = model_path or find_model_path()
    if path is None:
        raise FileNotFoundError(
            "No trained model artifact found. Run scripts/train_xgboost_price_model.py "
            "or scripts/run_postgres_ml_test.py first."
        )
    return joblib.load(path), path


def build_prediction_features(payload: PricePredictionInput) -> pd.DataFrame:
    row: dict[str, Any] = {
        "Diện tích trị": payload.area_m2,
        "Latitude": payload.latitude,
        "Longitude": payload.longitude,
        "dist_to_HN_center": haversine_km(payload.latitude, payload.longitude, THAP_RUA_LAT, THAP_RUA_LON),
        "Huyện": payload.district,
        "ward": payload.ward,
        "Số phòng ngủ": _format_count_label(payload.bedrooms, "phòng"),
        "Mặt tiền": _format_meter_label(payload.front_length_m),
        "Đường vào": _format_meter_label(payload.road_size_m),
        "Số tầng": payload.floors,
        "Số toilet": payload.toilets,
        "Pháp lý": normalize_legal_status_for_ml(payload.legal_status),
    }
    row.update(_accessibility_feature_values(payload.latitude, payload.longitude))
    frame = pd.DataFrame([row])
    for column in MODEL_FEATURES:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[MODEL_FEATURES]


def predict_price(payload: PricePredictionInput, model_path: Path | None = None) -> PricePredictionResult:
    model, resolved_model_path = load_price_model(model_path)
    features = build_prediction_features(payload)
    price_per_m2 = float(model.predict(features)[0])
    total_price_billion = price_per_m2 * payload.area_m2 / 1000.0
    return PricePredictionResult(
        price_per_m2_million_vnd=price_per_m2,
        total_price_billion_vnd=total_price_billion,
        features=features,
        model_path=resolved_model_path,
    )


def estimate_location_from_training_data(
    df: pd.DataFrame,
    *,
    district: str,
    ward: str | None = None,
) -> tuple[float, float] | None:
    if df.empty or "Latitude" not in df.columns or "Longitude" not in df.columns:
        return None
    working = df.copy()
    working["Latitude"] = pd.to_numeric(working["Latitude"], errors="coerce")
    working["Longitude"] = pd.to_numeric(working["Longitude"], errors="coerce")
    working = working.dropna(subset=["Latitude", "Longitude"])
    if district and "Huyện" in working.columns:
        working = working[working["Huyện"].astype(str) == str(district)]
    if ward and "ward" in working.columns:
        ward_rows = working[working["ward"].astype(str) == str(ward)]
        if not ward_rows.empty:
            working = ward_rows
    if working.empty:
        return None
    return float(working["Latitude"].median()), float(working["Longitude"].median())


def candidate_locations_from_training_data(
    df: pd.DataFrame,
    *,
    district: str,
    ward: str | None = None,
    limit: int = 6,
) -> list[LocationOption]:
    if df.empty or "Latitude" not in df.columns or "Longitude" not in df.columns:
        return []
    working = df.copy()
    working["Latitude"] = pd.to_numeric(working["Latitude"], errors="coerce")
    working["Longitude"] = pd.to_numeric(working["Longitude"], errors="coerce")
    working = working.dropna(subset=["Latitude", "Longitude"])
    if district and "Huyện" in working.columns:
        working = working[working["Huyện"].astype(str) == str(district)]
    if ward and "ward" in working.columns:
        ward_rows = working[working["ward"].astype(str) == str(ward)]
        if not ward_rows.empty:
            working = ward_rows
    if working.empty:
        return []

    sample = working[["Latitude", "Longitude"]].drop_duplicates().head(limit)
    options: list[LocationOption] = []
    for index, row in enumerate(sample.itertuples(index=False), start=1):
        options.append(
            LocationOption(
                label=f"Sample point {index}",
                latitude=float(row.Latitude),
                longitude=float(row.Longitude),
            )
        )
    return options


def location_preview_deck(latitude: float, longitude: float) -> Any:
    import pydeck as pdk

    return location_preview_deck_with_candidates(latitude, longitude, [])


def location_preview_deck_with_candidates(
    latitude: float,
    longitude: float,
    candidates: list[LocationOption],
) -> Any:
    import pydeck as pdk

    point_rows = [
        {"Latitude": latitude, "Longitude": longitude, "kind": "selected", "color": [220, 50, 47, 220], "radius": 140},
    ]
    for candidate in candidates:
        point_rows.append(
            {
                "Latitude": candidate.latitude,
                "Longitude": candidate.longitude,
                "kind": candidate.label,
                "color": [52, 152, 219, 160],
                "radius": 90,
            }
        )
    point_df = pd.DataFrame(point_rows)
    layer = pdk.Layer(
        "ScatterplotLayer",
        point_df,
        get_position="[Longitude, Latitude]",
        get_fill_color="color",
        get_radius="radius",
        radius_min_pixels=7,
        radius_max_pixels=16,
        pickable=False,
    )
    return pdk.Deck(
        map_style=pdk.map_styles.CARTO_LIGHT,
        initial_view_state=pdk.ViewState(
            latitude=latitude,
            longitude=longitude,
            zoom=13,
            pitch=0,
            bearing=0,
        ),
        layers=[layer],
    )


def location_click_map(
    latitude: float,
    longitude: float,
    *,
    candidates: list[LocationOption] | None = None,
    height: int = 520,
) -> dict[str, float] | None:
    candidates = candidates or []
    center_lat = latitude
    center_lon = longitude
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=14, control_scale=True)

    folium.Marker(
        location=[latitude, longitude],
        tooltip="Selected point",
        icon=folium.Icon(color="red", icon="map-marker"),
    ).add_to(fmap)

    for candidate in candidates:
        folium.CircleMarker(
            location=[candidate.latitude, candidate.longitude],
            radius=6,
            color="#3182bd",
            fill=True,
            fill_opacity=0.8,
            tooltip=candidate.label,
        ).add_to(fmap)

    result = st_folium(fmap, height=height, width=None, returned_objects=["last_clicked"])
    last_clicked = result.get("last_clicked") if isinstance(result, dict) else None
    if not last_clicked:
        return None
    lat = last_clicked.get("lat")
    lng = last_clicked.get("lng")
    if lat is None or lng is None:
        return None
    return {"latitude": float(lat), "longitude": float(lng)}


def resolve_admin_location_from_point(
    latitude: float,
    longitude: float,
    *,
    training_df: pd.DataFrame | None = None,
) -> ResolvedAdminLocation:
    district, district_source = _resolve_district_from_point(latitude, longitude)
    ward, ward_source = _resolve_ward_from_point(latitude, longitude)

    if not ward and training_df is not None and district:
        ward = _infer_ward_from_training_data(training_df, latitude, longitude, district)
        if ward:
            ward_source = "nearest_training_sample"

    return ResolvedAdminLocation(
        district=district,
        ward=ward,
        district_source=district_source,
        ward_source=ward_source,
    )


def _accessibility_feature_values(latitude: float, longitude: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    point = gpd.GeoDataFrame(
        [{"Latitude": latitude, "Longitude": longitude}],
        geometry=gpd.points_from_xy([longitude], [latitude], crs=WGS84_CRS),
        crs=WGS84_CRS,
    ).to_crs(METRIC_CRS)
    point_geom = point.geometry.iloc[0]
    buffer_geom = point_geom.buffer(1000.0)

    for layer, path in ACCESSIBILITY_LAYER_FILES.items():
        prefix = FEATURE_PREFIX_BY_LAYER[layer]
        distance_column = f"dist_nearest_{prefix}_m"
        count_column = f"{prefix}_count_1000m"
        try:
            pois = load_accessibility_layer(layer).to_crs(METRIC_CRS)
        except (FileNotFoundError, OSError, ValueError):
            result[distance_column] = math.nan
            result[count_column] = 0
            continue
        pois = pois[pois.geometry.notna()].copy()
        if pois.empty:
            result[distance_column] = math.nan
            result[count_column] = 0
            continue
        distances = pois.geometry.distance(point_geom)
        result[distance_column] = float(distances.min())
        result[count_column] = int(pois.geometry.intersects(buffer_geom).sum())
    return result


def _resolve_district_from_point(latitude: float, longitude: float) -> tuple[str | None, str | None]:
    districts = load_hanoi_districts()
    if not districts.empty and "geometry" in districts.columns:
        point_gdf = gpd.GeoDataFrame(
            [{"Latitude": latitude, "Longitude": longitude}],
            geometry=gpd.points_from_xy([longitude], [latitude], crs=WGS84_CRS),
            crs=WGS84_CRS,
        ).to_crs(METRIC_CRS)
        districts_metric = districts[["district_name", "district_name_normalized", "geometry"]].copy().to_crs(METRIC_CRS)
        joined = gpd.sjoin(
            point_gdf,
            districts_metric,
            how="left",
            predicate="intersects",
        )
        if not joined.empty:
            district_name = _canonicalize_district_name(clean_text(joined.iloc[0].get("district_name")), districts)
            if district_name:
                return district_name, "district_polygon"

        nearest = gpd.sjoin_nearest(
            point_gdf[["geometry"]],
            districts_metric,
            how="left",
            distance_col="_distance_m",
        )
        if not nearest.empty:
            district_name = _canonicalize_district_name(clean_text(nearest.iloc[0].get("district_name")), districts)
            if district_name:
                return district_name, "district_nearest_polygon"

    payload = _reverse_geocode_point(latitude, longitude)
    address = payload.get("address") if isinstance(payload, dict) else {}
    if isinstance(address, dict):
        district_candidate = _first_meaningful_address_component(
            address,
            ["county", "city_district", "state_district", "municipality"],
        )
        district_name = _canonicalize_district_name(district_candidate, districts)
        if district_name:
            return district_name, "reverse_geocode"
    return None, None


def _resolve_ward_from_point(latitude: float, longitude: float) -> tuple[str | None, str | None]:
    payload = _reverse_geocode_point(latitude, longitude)
    address = payload.get("address") if isinstance(payload, dict) else {}
    if not isinstance(address, dict):
        return None, None

    ward_candidate = _first_meaningful_address_component(
        address,
        ["suburb", "quarter", "neighbourhood", "neighborhood", "hamlet", "village", "town", "locality"],
    )
    if ward_candidate:
        return ward_candidate, "reverse_geocode"
    return None, None


def _infer_ward_from_training_data(
    training_df: pd.DataFrame,
    latitude: float,
    longitude: float,
    district: str,
    *,
    max_distance_km: float = 1.5,
) -> str | None:
    if training_df.empty or "ward" not in training_df.columns or "Latitude" not in training_df.columns:
        return None

    working = training_df.copy()
    working["Latitude"] = pd.to_numeric(working["Latitude"], errors="coerce")
    working["Longitude"] = pd.to_numeric(working["Longitude"], errors="coerce")
    working = working.dropna(subset=["Latitude", "Longitude", "ward"]).copy()
    if working.empty:
        return None

    target_district = normalize_district_name(district)
    if target_district and "Huyện" in working.columns:
        working["_district_normalized"] = working["Huyện"].apply(normalize_district_name)
        working = working[working["_district_normalized"] == target_district].copy()
    if working.empty:
        return None

    working["_distance_km"] = working.apply(
        lambda row: haversine_km(latitude, longitude, float(row["Latitude"]), float(row["Longitude"])),
        axis=1,
    )
    nearest = working.sort_values("_distance_km", ascending=True).iloc[0]
    if float(nearest["_distance_km"]) <= max_distance_km:
        ward = clean_text(nearest.get("ward"))
        return ward
    return None


@lru_cache(maxsize=4096)
def _reverse_geocode_point(latitude: float, longitude: float) -> dict[str, Any]:
    rounded_lat = round(float(latitude), 5)
    rounded_lon = round(float(longitude), 5)
    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={
                "format": "jsonv2",
                "lat": rounded_lat,
                "lon": rounded_lon,
                "addressdetails": 1,
                "zoom": 18,
                "accept-language": "vi",
            },
            headers={
                "User-Agent": "HanoiRealEstatePrices/1.0 (Streamlit predictor)",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except (requests.RequestException, ValueError):
        return {}
    return {}


def _first_meaningful_address_component(address: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = clean_text(address.get(key))
        if not value:
            continue
        normalized = normalize_district_name(value)
        if normalized in {"ha noi", "hanoi", "thanh pho ha noi"}:
            continue
        return value
    return None


def _canonicalize_district_name(value: str | None, districts: gpd.GeoDataFrame) -> str | None:
    if not value:
        return None
    target = normalize_district_name(value)
    if not target:
        return None
    candidates = districts["district_name"].astype(str).tolist() if "district_name" in districts.columns else []
    normalized_lookup = {
        normalize_district_name(candidate): candidate
        for candidate in candidates
        if normalize_district_name(candidate)
    }
    return normalized_lookup.get(target)


def _format_meter_label(value: float | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    return f"{float(value):.2f} m".replace(".", ",")


def _format_count_label(value: str | float | int | None, suffix: str) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(suffix):
        return text
    try:
        number = int(float(text))
    except ValueError:
        return text
    return f"{number} {suffix}"
