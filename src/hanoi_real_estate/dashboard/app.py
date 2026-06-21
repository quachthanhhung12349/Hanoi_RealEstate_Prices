from __future__ import annotations

import math
import sqlite3
from typing import Any

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from hanoi_real_estate.analytics import (
    build_correlation_dataframe,
    build_region_stats_dataframe,
    build_table_dataframe,
    load_dashboard_dataframe,
)
from hanoi_real_estate.db import get_dashboard_data_version, get_gis_cache_version
from hanoi_real_estate.gis import (
    build_boundary_validation_dataframe,
    build_district_validation_dataframe,
    build_district_price_geojson,
    build_district_price_dataframe,
    build_interpolated_price_surface_dataframe,
    build_pydeck_point_dataframe,
    get_hanoi_center_view_state,
    load_cached_gis_district_choropleth,
    load_cached_gis_district_price_dataframe,
    load_cached_gis_price_surface_dataframe,
    load_hanoi_boundary_geojson,
    load_hanoi_districts_geojson,
)
from hanoi_real_estate.ml.prediction import (
    PricePredictionInput,
    candidate_locations_from_training_data,
    estimate_location_from_training_data,
    find_model_path,
    location_click_map,
    resolve_admin_location_from_point,
    predict_price,
)
from hanoi_real_estate.features.ml_dataset import normalize_legal_status_for_ml


class DashboardDataError(RuntimeError):
    pass


st.set_page_config(
    page_title="Hanoi Real Estate Dashboard",
    page_icon="🏠",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def load_core_data(
    active_only: bool,
    data_version: str,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    try:
        base_df = load_dashboard_dataframe(active_only=active_only)
        table_df = build_table_dataframe(base_df)
        correlation_df = build_correlation_dataframe(base_df)
        region_stats_df = build_region_stats_dataframe(base_df)
    except (sqlite3.Error, SQLAlchemyError, OSError, ValueError, KeyError) as exc:
        raise DashboardDataError(_friendly_data_error(exc)) from exc
    return (
        base_df,
        table_df,
        correlation_df,
        region_stats_df,
    )


@st.cache_data(show_spinner=False)
def load_gis_layers(
    _base_df: pd.DataFrame,
    active_only: bool,
    data_version: str,
    gis_cache_version: str,
    include_surface: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        if include_surface:
            gis_surface_df = load_cached_gis_price_surface_dataframe()
            if gis_surface_df.empty:
                gis_surface_df = build_interpolated_price_surface_dataframe(
                    _base_df,
                    active_only=active_only,
                    cell_size_meters=800.0,
                )
        else:
            gis_surface_df = pd.DataFrame(
                columns=[
                    "Longitude",
                    "Latitude",
                    "predicted_price_per_m2",
                    "cell_polygon",
                ]
            )
        gis_district_price_df = load_cached_gis_district_price_dataframe()
        if gis_district_price_df.empty:
            gis_district_price_df = build_district_price_dataframe(
                _base_df,
                active_only=active_only,
            )
        hanoi_boundary_geojson = load_hanoi_boundary_geojson()
        hanoi_districts_geojson = load_hanoi_districts_geojson()
        district_price_geojson = load_cached_gis_district_choropleth()
        if _needs_district_choropleth_rebuild(district_price_geojson) and not gis_district_price_df.empty:
            district_price_geojson = build_district_price_geojson(
                hanoi_districts_geojson,
                gis_district_price_df,
            )
    except (sqlite3.Error, SQLAlchemyError, OSError, ValueError, KeyError) as exc:
        raise DashboardDataError(_friendly_data_error(exc)) from exc
    return (
        gis_surface_df,
        gis_district_price_df,
        district_price_geojson,
        hanoi_boundary_geojson,
        hanoi_districts_geojson,
    )


@st.cache_data(show_spinner=False)
def load_gis_listing_data(
    _base_df: pd.DataFrame,
    active_only: bool,
    data_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        gis_points_df = build_pydeck_point_dataframe(_base_df)
        gis_validation_df = build_boundary_validation_dataframe(_base_df, active_only=active_only)
        gis_district_validation_df = build_district_validation_dataframe(_base_df, active_only=active_only)
    except (sqlite3.Error, SQLAlchemyError, OSError, ValueError, KeyError) as exc:
        raise DashboardDataError(_friendly_data_error(exc)) from exc
    return gis_points_df, gis_validation_df, gis_district_validation_df


def apply_filters(
    base_df: pd.DataFrame,
    table_df: pd.DataFrame,
    correlation_df: pd.DataFrame,
    region_stats_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    st.sidebar.header("Filters")

    districts = sorted(
        value for value in base_df.get("Huyện", pd.Series(dtype="object")).dropna().astype(str).unique() if value
    )
    selected_districts = st.sidebar.multiselect("Huyện", districts)

    legal_statuses = sorted(
        value for value in base_df.get("Pháp lý", pd.Series(dtype="object")).dropna().astype(str).unique() if value
    )
    selected_legal = st.sidebar.multiselect("Pháp lý", legal_statuses)

    ad_types = sorted(
        value for value in base_df.get("Loại tin", pd.Series(dtype="object")).dropna().astype(str).unique() if value
    )
    selected_ad_types = st.sidebar.multiselect("Loại tin", ad_types)

    min_price, max_price = _range_from_series(base_df.get("Mức giá trị", pd.Series(dtype="float64")))
    selected_price = st.sidebar.slider(
        "Mức giá (tỷ VND)",
        min_value=min_price,
        max_value=max_price,
        value=(min_price, max_price),
        step=0.5,
    )

    min_area, max_area = _range_from_series(base_df.get("Diện tích trị", pd.Series(dtype="float64")))
    selected_area = st.sidebar.slider(
        "Diện tích (m²)",
        min_value=min_area,
        max_value=max_area,
        value=(min_area, max_area),
        step=5.0,
    )

    filtered_base = base_df.copy()
    if selected_districts:
        filtered_base = filtered_base[filtered_base["Huyện"].isin(selected_districts)]
    if selected_legal:
        filtered_base = filtered_base[filtered_base["Pháp lý"].isin(selected_legal)]
    if selected_ad_types:
        filtered_base = filtered_base[filtered_base["Loại tin"].isin(selected_ad_types)]

    filtered_base = filtered_base[
        filtered_base["Mức giá trị"].fillna(-math.inf).between(selected_price[0], selected_price[1])
    ]
    filtered_base = filtered_base[
        filtered_base["Diện tích trị"].fillna(-math.inf).between(selected_area[0], selected_area[1])
    ]

    listing_ids = set(filtered_base["Mã tin"].astype(str))

    filtered_table = table_df[table_df["Mã tin"].astype(str).isin(listing_ids)].copy()
    filtered_correlation = correlation_df[
        correlation_df["Mã tin"].astype(str).isin(listing_ids)
    ].copy()
    filtered_region_stats = _rebuild_region_stats_from_filtered_base(filtered_base, region_stats_df)

    return filtered_base, filtered_table, filtered_correlation, filtered_region_stats


def render_overview(base_df: pd.DataFrame, correlation_df: pd.DataFrame, region_stats_df: pd.DataFrame) -> None:
    total_listings = len(base_df)
    districts = base_df["Huyện"].dropna().nunique() if not base_df.empty else 0
    avg_price_billion = base_df["Mức giá trị"].dropna().mean() if not base_df.empty else math.nan
    avg_price_m2 = base_df["Giá/m² trị"].dropna().mean() if not base_df.empty else math.nan

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Listings", f"{total_listings:,}")
    col2.metric("Districts", f"{districts:,}")
    col3.metric("Avg price", _format_metric(avg_price_billion, "tỷ"))
    col4.metric("Avg price / m²", _format_metric(avg_price_m2, "triệu"))

    if not correlation_df.empty:
        st.caption(f"Correlation dataset rows after notebook-style cleaning: {len(correlation_df):,}")
    if not region_stats_df.empty:
        st.caption(f"Regions with statistics: {len(region_stats_df):,}")


def render_table_tab(table_df: pd.DataFrame) -> None:
    st.subheader("Listing Table")
    st.dataframe(table_df, use_container_width=True, hide_index=True)


def render_correlation_tab(correlation_df: pd.DataFrame) -> None:
    st.subheader("Distance to Hanoi Center vs Price per m²")
    if correlation_df.empty:
        st.info("No data available for the correlation plot.")
        return

    fig = px.scatter(
        correlation_df,
        x="dist_to_HN_center",
        y="Giá/m²",
        hover_data=["Mã tin", "Địa chỉ", "Latitude", "Longitude"],
        labels={
            "dist_to_HN_center": "Distance to Hanoi center (km)",
            "Giá/m²": "Price per m² (million VND/m²)",
        },
        opacity=0.55,
    )
    fig.update_yaxes(type="log")
    fig.update_layout(height=560, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_region_stats_tab(region_stats_df: pd.DataFrame) -> None:
    st.subheader("Regional Statistics")
    if region_stats_df.empty:
        st.info("No region statistics available.")
        return

    col1, col2 = st.columns(2)

    with col1:
        price_per_m2_fig = px.bar(
            region_stats_df,
            x="Huyện",
            y="avg_price_per_m2_million_vnd",
            hover_data=["listing_count"],
            labels={
                "Huyện": "District",
                "avg_price_per_m2_million_vnd": "Avg price / m² (million VND)",
            },
        )
        price_per_m2_fig.update_layout(height=480, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(price_per_m2_fig, use_container_width=True)

    with col2:
        total_price_fig = px.bar(
            region_stats_df,
            x="Huyện",
            y="avg_price_billion_vnd",
            hover_data=["listing_count"],
            labels={
                "Huyện": "District",
                "avg_price_billion_vnd": "Avg total price (billion VND)",
            },
        )
        total_price_fig.update_layout(height=480, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(total_price_fig, use_container_width=True)

    display_df = region_stats_df.rename(
        columns={
            "avg_price_billion_vnd": "Avg total price (tỷ VND)",
            "avg_price_per_m2_million_vnd": "Avg price / m² (triệu VND)",
            "listing_count": "Listing count",
        }
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_price_predictor_tab(base_df: pd.DataFrame) -> None:
    st.subheader("Price Predictor")
    model_path = find_model_path()
    if model_path is None:
        st.warning("No trained model artifact was found.")
        st.caption(
            "Train a model with `PYTHONPATH=src python scripts/run_postgres_ml_test.py` "
            "or place `xgboost_price_per_m2_pipeline.joblib` in `models/`."
        )
        return

    prediction_df = base_df.dropna(subset=["Huyện", "ward", "Latitude", "Longitude"]).copy()
    if prediction_df.empty:
        st.info("No geocoded ward/district data is available for location estimation yet.")
        return

    districts = sorted(prediction_df["Huyện"].dropna().astype(str).unique())
    left, right = st.columns([0.9, 1.1])

    with left:
        selected_district = st.session_state.get("predictor_district")
        if selected_district not in districts:
            selected_district = districts[0]
        district = st.selectbox("District", districts, index=districts.index(selected_district))

        ward_options = sorted(
            prediction_df.loc[prediction_df["Huyện"].astype(str) == district, "ward"]
            .dropna()
            .astype(str)
            .unique()
        )
        selected_ward = st.session_state.get("predictor_ward")
        if selected_ward not in ward_options:
            selected_ward = ward_options[0] if ward_options else ""
        ward = st.selectbox("Ward", ward_options, index=ward_options.index(selected_ward)) if ward_options else ""

        estimate = estimate_location_from_training_data(prediction_df, district=district, ward=ward or None)
        if estimate is None:
            estimate = (21.0255923, 105.8464321)

        location_mode = st.radio(
            "Location source",
            ["Click on map", "Estimate from ward", "Manual coordinates"],
            horizontal=True,
        )
        suggested_points = candidate_locations_from_training_data(prediction_df, district=district, ward=ward)
        if location_mode == "Click on map":
            if "predictor_latitude" not in st.session_state:
                st.session_state["predictor_latitude"] = float(estimate[0])
            if "predictor_longitude" not in st.session_state:
                st.session_state["predictor_longitude"] = float(estimate[1])
            click_result = location_click_map(
                float(st.session_state["predictor_latitude"]),
                float(st.session_state["predictor_longitude"]),
                candidates=suggested_points,
            )
            if click_result:
                st.session_state["predictor_latitude"] = click_result["latitude"]
                st.session_state["predictor_longitude"] = click_result["longitude"]
                resolved = resolve_admin_location_from_point(
                    click_result["latitude"],
                    click_result["longitude"],
                    training_df=prediction_df,
                )
                if resolved.district and resolved.district in districts:
                    st.session_state["predictor_district"] = resolved.district
                if resolved.ward:
                    ward_scope = prediction_df.loc[
                        prediction_df["Huyện"].astype(str) == st.session_state.get("predictor_district", resolved.district or district),
                        "ward",
                    ].dropna().astype(str).unique().tolist()
                    if resolved.ward in ward_scope:
                        st.session_state["predictor_ward"] = resolved.ward
                st.rerun()
            latitude = float(st.session_state["predictor_latitude"])
            longitude = float(st.session_state["predictor_longitude"])
            resolved = resolve_admin_location_from_point(latitude, longitude, training_df=prediction_df)
            if resolved.district and resolved.district in districts:
                district = resolved.district
                st.session_state["predictor_district"] = district
            ward_scope = prediction_df.loc[
                prediction_df["Huyện"].astype(str) == district,
                "ward",
            ].dropna().astype(str).unique().tolist()
            if resolved.ward and resolved.ward in ward_scope:
                ward = resolved.ward
                st.session_state["predictor_ward"] = ward
            st.caption("Click the map to move the selected building point.")
        elif location_mode == "Manual coordinates":
            lat_col, lon_col = st.columns(2)
            latitude = lat_col.number_input("Latitude", value=float(estimate[0]), format="%.7f")
            longitude = lon_col.number_input("Longitude", value=float(estimate[1]), format="%.7f")
            resolved = resolve_admin_location_from_point(latitude, longitude, training_df=prediction_df)
            if resolved.district and resolved.district in districts:
                district = resolved.district
                st.session_state["predictor_district"] = district
            ward_scope = prediction_df.loc[
                prediction_df["Huyện"].astype(str) == district,
                "ward",
            ].dropna().astype(str).unique().tolist()
            if resolved.ward and resolved.ward in ward_scope:
                ward = resolved.ward
                st.session_state["predictor_ward"] = ward
        else:
            latitude, longitude = estimate
            st.caption(f"Estimated point: {latitude:.6f}, {longitude:.6f}")
            resolved = resolve_admin_location_from_point(latitude, longitude, training_df=prediction_df)
            if resolved.district and resolved.district in districts:
                district = resolved.district
                st.session_state["predictor_district"] = district
            ward_scope = prediction_df.loc[
                prediction_df["Huyện"].astype(str) == district,
                "ward",
            ].dropna().astype(str).unique().tolist()
            if resolved.ward and resolved.ward in ward_scope:
                ward = resolved.ward
                st.session_state["predictor_ward"] = ward

        if "predictor_district" not in st.session_state:
            st.session_state["predictor_district"] = district
        if "predictor_ward" not in st.session_state:
            st.session_state["predictor_ward"] = ward

        st.caption(
            f"Resolved location: {district}"
            + (f" / {ward}" if ward else "")
            + (f" | source: {resolved.district_source or 'n/a'}"
               if 'resolved' in locals() and resolved.district_source else "")
        )

        area_m2 = st.number_input("Building area (m²)", min_value=1.0, max_value=2000.0, value=60.0, step=5.0)
        floor_col, bedroom_col = st.columns(2)
        floors = floor_col.number_input("Floors", min_value=1.0, max_value=30.0, value=5.0, step=1.0)
        bedrooms = bedroom_col.number_input("Bedrooms", min_value=0, max_value=20, value=4, step=1)
        frontage_col, road_col = st.columns(2)
        front_length_m = frontage_col.number_input("Frontage (m)", min_value=0.0, max_value=100.0, value=5.0, step=0.5)
        road_size_m = road_col.number_input("Road width (m)", min_value=0.0, max_value=100.0, value=4.0, step=0.5)

        legal_statuses = ["Sổ đỏ/Sổ hồng", "Chưa sổ"]
        legal_status = st.selectbox("Legal status", legal_statuses)

    with right:
        if location_mode != "Click on map":
            st.pydeck_chart(
                location_preview_deck_with_candidates(float(latitude), float(longitude), suggested_points),
                use_container_width=True,
            )
        else:
            st.caption(f"Selected point: {float(latitude):.6f}, {float(longitude):.6f}")

    payload = PricePredictionInput(
        district=district,
        ward=ward or "",
        latitude=float(latitude),
        longitude=float(longitude),
        area_m2=float(area_m2),
        bedrooms=str(bedrooms),
        front_length_m=float(front_length_m) if front_length_m else None,
        road_size_m=float(road_size_m) if road_size_m else None,
        floors=float(floors),
        legal_status=normalize_legal_status_for_ml(legal_status),
    )

    try:
        result = predict_price(payload, model_path=model_path)
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        st.error("The predictor could not run.")
        st.caption(str(exc))
        return

    metric_cols = st.columns(3)
    metric_cols[0].metric("Predicted price / m²", _format_metric(result.price_per_m2_million_vnd, "triệu"))
    metric_cols[1].metric("Estimated total price", _format_metric(result.total_price_billion_vnd, "tỷ"))
    metric_cols[2].metric("Model", model_path.parent.name)
    st.caption(f"Model artifact: {model_path}")

    with st.expander("Feature values used for prediction"):
        st.dataframe(result.features, use_container_width=True, hide_index=True)


def render_gis_tab(
    gis_points_df: pd.DataFrame,
    gis_surface_df: pd.DataFrame,
    gis_district_price_df: pd.DataFrame,
    gis_validation_df: pd.DataFrame,
    gis_district_validation_df: pd.DataFrame,
    district_price_geojson: dict,
    hanoi_boundary_geojson: dict,
    hanoi_districts_geojson: dict,
    layer_mode: str,
) -> None:
    st.subheader("GIS Preview")
    if gis_points_df.empty:
        st.info("No geocoded listings available for the GIS preview yet.")
        return

    validation_lookup = gis_validation_df[["Mã tin", "inside_hanoi"]].copy()
    district_lookup = gis_district_validation_df[["Mã tin", "district_osm", "district_match"]].copy()
    point_map_df = gis_points_df.merge(validation_lookup, on="Mã tin", how="left")
    point_map_df = point_map_df.merge(district_lookup, on="Mã tin", how="left")
    point_map_df["inside_hanoi"] = point_map_df["inside_hanoi"].eq(True)
    point_map_df["district_match"] = point_map_df["district_match"].eq(True)
    has_district_polygon = point_map_df["district_osm"].notna()
    district_mismatch_mask = point_map_df["inside_hanoi"] & has_district_polygon & ~point_map_df["district_match"]
    outside_mask = ~point_map_df["inside_hanoi"]
    point_map_df["point_color"] = [[39, 174, 96, 210]] * len(point_map_df)
    point_map_df.loc[district_mismatch_mask, "point_color"] = pd.Series(
        [[243, 156, 18, 210]] * int(district_mismatch_mask.sum()),
        index=point_map_df.index[district_mismatch_mask],
    )
    point_map_df.loc[outside_mask, "point_color"] = pd.Series(
        [[231, 76, 60, 210]] * int(outside_mask.sum()),
        index=point_map_df.index[outside_mask],
    )
    point_map_df["tooltip_status"] = "Inside Hanoi and district text matches polygon."
    point_map_df.loc[district_mismatch_mask, "tooltip_status"] = "District text differs from containing polygon."
    point_map_df.loc[outside_mask, "tooltip_status"] = "Outside Hanoi boundary."

    geojson_layer = pdk.Layer(
        "GeoJsonLayer",
        hanoi_boundary_geojson,
        stroked=True,
        filled=True,
        get_fill_color=[52, 152, 219, 20],
        get_line_color=[41, 128, 185, 180],
        line_width_min_pixels=2,
        pickable=True,
    )
    district_layer = pdk.Layer(
        "GeoJsonLayer",
        hanoi_districts_geojson,
        stroked=True,
        filled=False,
        get_line_color=[127, 140, 141, 110],
        line_width_min_pixels=1,
        pickable=True,
    )
    point_layer = pdk.Layer(
        "ScatterplotLayer",
        point_map_df,
        get_position="[Longitude, Latitude]",
        get_fill_color="point_color",
        get_radius=60,
        radius_min_pixels=3,
        radius_max_pixels=8,
        pickable=True,
    )
    surface_df = pd.DataFrame()
    if layer_mode == "Interpolated price surface":
        surface_df = gis_surface_df.copy()
    if layer_mode == "Interpolated price surface" and not surface_df.empty:
        surface_df = surface_df[
            surface_df["cell_polygon"].apply(_is_valid_polygon_ring)
            & pd.to_numeric(surface_df["predicted_price_per_m2"], errors="coerce").notna()
        ].copy()
        surface_df["fill_color"] = surface_df["predicted_price_per_m2"].apply(_price_to_color)
    layers = [geojson_layer, district_layer]
    if layer_mode == "Interpolated price surface" and not surface_df.empty:
        layers.append(
            pdk.Layer(
                "PolygonLayer",
                surface_df,
                get_polygon="cell_polygon",
                get_fill_color="fill_color",
                get_line_color=[255, 255, 255, 0],
                stroked=False,
                filled=True,
                opacity=0.65,
                pickable=True,
            )
        )
    elif layer_mode == "District average" and district_price_geojson["features"]:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                district_price_geojson,
                stroked=True,
                filled=True,
                get_fill_color="properties.fill_color",
                get_line_color=[99, 99, 99, 140],
                line_width_min_pixels=1,
                pickable=True,
            )
        )
    layers.append(point_layer)

    deck = pdk.Deck(
        map_style=pdk.map_styles.CARTO_LIGHT,
        initial_view_state=pdk.ViewState(**get_hanoi_center_view_state()),
        layers=layers,
        tooltip={
            "html": (
                "<b>{district_name}</b><br/>"
                "District avg: {avg_price_per_m2} triệu/m²<br/>"
                "Listings: {listing_count}<br/>"
                "<hr style='margin:0.3rem 0;'/>"
                "<b>{Tiêu đề}</b><br/>"
                "{Địa chỉ}<br/>"
                "District text: {Huyện}<br/>"
                "District polygon: {district_osm}<br/>"
                "Price/m²: {tooltip_price_per_m2}<br/>"
                "Total price: {tooltip_total_price}<br/>"
                "{tooltip_status}"
            )
        },
    )
    st.pydeck_chart(deck, use_container_width=True)

    inside_count = int(point_map_df["inside_hanoi"].sum())
    outside_count = int(outside_mask.sum())
    district_mismatch_count = int(district_mismatch_mask.sum())
    col1, col2, col3 = st.columns(3)
    col1.metric("Geocoded points", f"{len(point_map_df):,}")
    col2.metric("Outside Hanoi boundary", f"{outside_count:,}")
    col3.metric("District mismatches", f"{district_mismatch_count:,}")
    st.caption(
        f"{inside_count:,} points fall inside the Hanoi boundary polygon. "
        "Red points are outside Hanoi, amber points are district mismatches, and green points passed both checks."
    )
    st.caption(
        "Use district average mode for a cleaner administrative-region summary."
    )
    if layer_mode == "Interpolated price surface":
        render_price_legend(surface_df, "predicted_price_per_m2", layer_mode)
    elif layer_mode == "District average":
        render_price_legend(gis_district_price_df, "avg_price_per_m2", layer_mode)

    if outside_count:
        outside_df = point_map_df.loc[
            ~point_map_df["inside_hanoi"],
            ["Mã tin", "Tiêu đề", "Địa chỉ", "Huyện", "Latitude", "Longitude", "Link"],
        ].copy()
        st.dataframe(outside_df, use_container_width=True, hide_index=True)

    if district_mismatch_count:
        mismatch_df = point_map_df.loc[
            point_map_df["inside_hanoi"]
            & point_map_df["district_osm"].notna()
            & ~point_map_df["district_match"],
            ["Mã tin", "Tiêu đề", "Địa chỉ", "Huyện", "district_osm", "Latitude", "Longitude", "Link"],
        ].copy()
        st.dataframe(mismatch_df, use_container_width=True, hide_index=True)


def main() -> None:
    st.title("Hanoi Real Estate Dashboard")

    active_only = st.sidebar.checkbox("Only active listings", value=True)
    try:
        data_version = get_dashboard_data_version()
        (
            base_df,
            table_df,
            correlation_df,
            region_stats_df,
        ) = load_core_data(active_only=active_only, data_version=data_version)
    except DashboardDataError as exc:
        st.error("The dashboard could not load the database.")
        st.caption(str(exc))
        st.info(
            "Initialize the local database with `PYTHONPATH=src python3 scripts/init_db.py`, "
            "provide `data/demo.sqlite3`, or configure `DATABASE_URL` for PostgreSQL."
        )
        return

    if base_df.empty:
        st.info("No dashboard data found yet.")
        st.caption(
            "Run the scraper/import scripts to populate the local SQLite database, "
            "add a demo database at `data/demo.sqlite3`, or point the app at PostgreSQL with `DATABASE_URL`."
        )
        return

    filtered_base, filtered_table, filtered_correlation, filtered_region_stats = apply_filters(
        base_df,
        table_df,
        correlation_df,
        region_stats_df,
    )

    render_overview(filtered_base, filtered_correlation, filtered_region_stats)

    selected_view = st.radio(
        "View",
        ["Price Predictor", "Table", "Distance vs Price/m²", "Regional Stats", "GIS Preview"],
        horizontal=True,
    )

    if selected_view == "Price Predictor":
        render_price_predictor_tab(base_df)
    elif selected_view == "Table":
        render_table_tab(filtered_table)
    elif selected_view == "Distance vs Price/m²":
        render_correlation_tab(filtered_correlation)
    elif selected_view == "Regional Stats":
        render_region_stats_tab(filtered_region_stats)
    else:
        layer_mode = st.radio(
            "Price layer",
            options=["District average", "Interpolated price surface", "Points only"],
            horizontal=True,
        )
        try:
            gis_cache_version = get_gis_cache_version()
            (
                gis_points_df,
                gis_validation_df,
                gis_district_validation_df,
            ) = load_gis_listing_data(
                base_df,
                active_only=active_only,
                data_version=data_version,
            )
            gis_surface_df, gis_district_price_df, district_price_geojson, hanoi_boundary_geojson, hanoi_districts_geojson = load_gis_layers(
                base_df,
                active_only=active_only,
                data_version=data_version,
                gis_cache_version=gis_cache_version,
                include_surface=layer_mode == "Interpolated price surface",
            )
        except DashboardDataError as exc:
            st.error("The GIS preview could not load.")
            st.caption(str(exc))
            return
        filtered_ids = set(filtered_base["Mã tin"].astype(str))
        filtered_gis_points = gis_points_df[gis_points_df["Mã tin"].astype(str).isin(filtered_ids)].copy()
        filtered_gis_surface = gis_surface_df
        filtered_gis_district_price = gis_district_price_df
        filtered_gis_validation = gis_validation_df[
            gis_validation_df["Mã tin"].astype(str).isin(filtered_ids)
        ].copy()
        filtered_gis_district_validation = gis_district_validation_df[
            gis_district_validation_df["Mã tin"].astype(str).isin(filtered_ids)
        ].copy()
        render_gis_tab(
            filtered_gis_points,
            filtered_gis_surface,
            filtered_gis_district_price,
            filtered_gis_validation,
            filtered_gis_district_validation,
            district_price_geojson,
            hanoi_boundary_geojson,
            hanoi_districts_geojson,
            layer_mode,
        )


def _range_from_series(series: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return 0.0, 1.0
    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if minimum == maximum:
        maximum = minimum + 1.0
    return minimum, maximum


def _friendly_data_error(exc: Exception) -> str:
    message = str(exc)
    if "no such table" in message:
        return (
            "The database exists, but the expected tables are missing. "
            "Run `PYTHONPATH=src python3 scripts/init_db.py`, initialize PostgreSQL with "
            "`sql/schema_postgres.sql`, or use the bundled demo database."
        )
    if "unable to open database file" in message:
        return "The SQLite database file could not be opened. Check the configured database path and file permissions."
    if "password authentication failed" in message or "connection refused" in message:
        return "The PostgreSQL connection failed. Check `DATABASE_URL`, database availability, and credentials."
    return message.splitlines()[0] if message else type(exc).__name__


def _needs_district_choropleth_rebuild(geojson_payload: dict[str, Any]) -> bool:
    features = geojson_payload.get("features")
    if not features:
        return True
    for feature in features:
        properties = feature.get("properties", {})
        if isinstance(properties, dict) and "fill_color" in properties:
            return False
    return True


def _is_valid_polygon_ring(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 4
        and all(
            isinstance(point, (list, tuple))
            and len(point) >= 2
            and pd.notna(point[0])
            and pd.notna(point[1])
            for point in value
        )
    )


def _rebuild_region_stats_from_filtered_base(
    filtered_base: pd.DataFrame,
    default_region_stats_df: pd.DataFrame,
) -> pd.DataFrame:
    if filtered_base.empty:
        return default_region_stats_df.iloc[0:0].copy()

    stats_df = filtered_base.copy()
    stats_df["Huyện"] = stats_df["Huyện"].fillna("Chưa rõ")
    grouped = (
        stats_df.groupby("Huyện", dropna=False)
        .agg(
            avg_price_billion_vnd=("Mức giá trị", "mean"),
            avg_price_per_m2_million_vnd=("Giá/m² trị", "mean"),
            listing_count=("Mã tin", "count"),
        )
        .reset_index()
        .sort_values(
            by=["avg_price_per_m2_million_vnd", "listing_count"],
            ascending=[False, False],
        )
        .reset_index(drop=True)
    )
    return grouped


def _format_metric(value: float, unit: str) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{value:,.2f} {unit}".replace(",", "X").replace(".", ",").replace("X", ".")


def _top_string_options(df: pd.DataFrame, column: str, *, default: str, limit: int = 12) -> list[str]:
    if column not in df.columns:
        return [default]
    values = df[column].dropna().astype(str)
    if values.empty:
        return [default]
    options = values.value_counts().head(limit).index.tolist()
    if default not in options:
        options.insert(0, default)
    return options


def _point_color_from_validation(row: pd.Series) -> list[int]:
    if row.get("inside_hanoi") is not True:
        return [231, 76, 60, 210]
    district_osm = row.get("district_osm")
    district_match = row.get("district_match")
    if pd.notna(district_osm) and not _is_truthy(district_match):
        return [243, 156, 18, 210]
    return [46, 204, 113, 180]


def _tooltip_status_from_validation(row: pd.Series) -> str:
    if row.get("inside_hanoi") is not True:
        return "Outside Hanoi boundary"
    district_osm = row.get("district_osm")
    district_match = row.get("district_match")
    if pd.notna(district_osm) and not _is_truthy(district_match):
        return "Inside Hanoi but mismatched district polygon"
    return "Passed boundary and district checks"


def _is_truthy(value: object) -> bool:
    if pd.isna(value):
        return False
    return bool(value)


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


def render_price_legend(source_df: pd.DataFrame, value_column: str, layer_mode: str) -> None:
    if source_df.empty:
        return

    values = pd.to_numeric(source_df[value_column], errors="coerce").dropna()
    if values.empty:
        return

    min_value = float(values.min())
    max_value = float(values.max())
    st.markdown(
        """
        <div style="margin-top:0.5rem;margin-bottom:0.5rem;font-size:0.95rem;font-weight:600;">
          Price Scale (million VND/m²)
        </div>
        <div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;margin-bottom:0.5rem;">
          <div style="text-align:center;">
            <div style="height:16px;border-radius:6px;background:#313695;"></div>
            <div style="font-size:0.8rem;"><=25</div>
          </div>
          <div style="text-align:center;">
            <div style="height:16px;border-radius:6px;background:#4575b4;"></div>
            <div style="font-size:0.8rem;">25-75</div>
          </div>
          <div style="text-align:center;">
            <div style="height:16px;border-radius:6px;background:#74add1;"></div>
            <div style="font-size:0.8rem;">75-150</div>
          </div>
          <div style="text-align:center;">
            <div style="height:16px;border-radius:6px;background:#abd9e9;"></div>
            <div style="font-size:0.8rem;">150-250</div>
          </div>
          <div style="text-align:center;">
            <div style="height:16px;border-radius:6px;background:#fdae61;"></div>
            <div style="font-size:0.8rem;">250-350</div>
          </div>
          <div style="text-align:center;">
            <div style="height:16px;border-radius:6px;background:#f03b20;"></div>
            <div style="font-size:0.8rem;">350+</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        f"{layer_mode}: approximately {min_value:,.1f} to {max_value:,.1f} million VND/m² across the visible price surface."
    )


if __name__ == "__main__":
    main()
