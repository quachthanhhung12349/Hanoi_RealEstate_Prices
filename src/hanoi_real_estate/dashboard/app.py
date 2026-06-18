from __future__ import annotations

import math
import sqlite3

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

from hanoi_real_estate.analytics import (
    build_correlation_dataframe,
    build_region_stats_dataframe,
    build_table_dataframe,
    load_dashboard_dataframe,
)
from hanoi_real_estate.gis import (
    build_boundary_validation_dataframe,
    build_district_validation_dataframe,
    build_district_price_dataframe,
    build_interpolated_price_surface_dataframe,
    build_pydeck_point_dataframe,
    get_hanoi_center_view_state,
    load_hanoi_boundary_geojson,
    load_hanoi_districts_geojson,
)


class DashboardDataError(RuntimeError):
    pass


st.set_page_config(
    page_title="Hanoi Real Estate Dashboard",
    page_icon="🏠",
    layout="wide",
)


@st.cache_data(ttl=120)
def load_data(
    active_only: bool,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict,
    dict,
]:
    try:
        base_df = load_dashboard_dataframe(active_only=active_only)
        table_df = build_table_dataframe(active_only=active_only)
        correlation_df = build_correlation_dataframe(active_only=active_only)
        region_stats_df = build_region_stats_dataframe(active_only=active_only)
        gis_points_df = build_pydeck_point_dataframe(active_only=active_only)
        gis_surface_df = build_interpolated_price_surface_dataframe(active_only=active_only)
        gis_district_price_df = build_district_price_dataframe(active_only=active_only)
        gis_validation_df = build_boundary_validation_dataframe(active_only=active_only)
        gis_district_validation_df = build_district_validation_dataframe(active_only=active_only)
        hanoi_boundary_geojson = load_hanoi_boundary_geojson()
        hanoi_districts_geojson = load_hanoi_districts_geojson()
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
        raise DashboardDataError(_friendly_data_error(exc)) from exc
    return (
        base_df,
        table_df,
        correlation_df,
        region_stats_df,
        gis_points_df,
        gis_surface_df,
        gis_district_price_df,
        gis_validation_df,
        gis_district_validation_df,
        hanoi_boundary_geojson,
        hanoi_districts_geojson,
    )


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


def render_gis_tab(
    gis_points_df: pd.DataFrame,
    gis_surface_df: pd.DataFrame,
    gis_district_price_df: pd.DataFrame,
    gis_validation_df: pd.DataFrame,
    gis_district_validation_df: pd.DataFrame,
    hanoi_boundary_geojson: dict,
    hanoi_districts_geojson: dict,
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
    point_map_df["point_color"] = point_map_df.apply(_point_color_from_validation, axis=1)
    point_map_df["tooltip_status"] = point_map_df.apply(_tooltip_status_from_validation, axis=1)

    layer_mode = st.radio(
        "Price layer",
        options=["Interpolated price surface", "District average", "Points only"],
        horizontal=True,
    )

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
    surface_df = gis_surface_df.copy()
    if not surface_df.empty:
        surface_df["fill_color"] = surface_df["predicted_price_per_m2"].apply(_price_to_color)
        surface_df["surface_polygon"] = surface_df["cell_polygon"].apply(lambda ring: [ring])
    district_geojson_data = _build_district_price_geojson(
        hanoi_districts_geojson,
        gis_district_price_df,
    )
    layers = [geojson_layer, district_layer]
    if layer_mode == "Interpolated price surface" and not surface_df.empty:
        layers.append(
            pdk.Layer(
                "PolygonLayer",
                surface_df,
                get_polygon="surface_polygon",
                get_fill_color="fill_color",
                get_line_color=[255, 255, 255, 0],
                stroked=False,
                filled=True,
                opacity=0.65,
                pickable=True,
            )
        )
    elif layer_mode == "District average" and district_geojson_data["features"]:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                district_geojson_data,
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
    outside_count = int((~point_map_df["inside_hanoi"]).sum())
    district_mismatch_count = int(
        (
            point_map_df["inside_hanoi"]
            & point_map_df["district_osm"].notna()
            & ~point_map_df["district_match"]
        ).sum()
    )
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
        (
            base_df,
            table_df,
            correlation_df,
            region_stats_df,
            gis_points_df,
            gis_surface_df,
            gis_district_price_df,
            gis_validation_df,
            gis_district_validation_df,
            hanoi_boundary_geojson,
            hanoi_districts_geojson,
        ) = load_data(active_only=active_only)
    except DashboardDataError as exc:
        st.error("The dashboard could not load the database.")
        st.caption(str(exc))
        st.info("Initialize the database with `PYTHONPATH=src python3 scripts/init_db.py`, or provide `data/demo.sqlite3` for demo data.")
        return

    if base_df.empty:
        st.info("No dashboard data found yet.")
        st.caption("Run the scraper/import scripts to populate the local SQLite database, or add a demo database at `data/demo.sqlite3`.")
        return

    filtered_base, filtered_table, filtered_correlation, filtered_region_stats = apply_filters(
        base_df,
        table_df,
        correlation_df,
        region_stats_df,
    )

    render_overview(filtered_base, filtered_correlation, filtered_region_stats)

    tab_table, tab_correlation, tab_region, tab_gis = st.tabs(
        ["Table", "Distance vs Price/m²", "Regional Stats", "GIS Preview"]
    )
    with tab_table:
        render_table_tab(filtered_table)
    with tab_correlation:
        render_correlation_tab(filtered_correlation)
    with tab_region:
        render_region_stats_tab(filtered_region_stats)
    with tab_gis:
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
            hanoi_boundary_geojson,
            hanoi_districts_geojson,
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
        return "The SQLite database exists, but the expected tables are missing. Run `PYTHONPATH=src python3 scripts/init_db.py` or use the bundled demo database."
    if "unable to open database file" in message:
        return "The SQLite database file could not be opened. Check the configured database path and file permissions."
    return message.splitlines()[0] if message else type(exc).__name__


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


def _build_district_price_geojson(district_geojson: dict, district_price_df: pd.DataFrame) -> dict:
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


if __name__ == "__main__":
    main()
