from __future__ import annotations

import math

import pandas as pd
import plotly.express as px
import streamlit as st

from hanoi_real_estate.analytics import (
    build_correlation_dataframe,
    build_region_stats_dataframe,
    build_table_dataframe,
    load_dashboard_dataframe,
)


st.set_page_config(
    page_title="Hanoi Real Estate Dashboard",
    page_icon="🏠",
    layout="wide",
)


@st.cache_data(ttl=120)
def load_data(active_only: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_df = load_dashboard_dataframe(active_only=active_only)
    table_df = build_table_dataframe(active_only=active_only)
    correlation_df = build_correlation_dataframe(active_only=active_only)
    region_stats_df = build_region_stats_dataframe(active_only=active_only)
    return base_df, table_df, correlation_df, region_stats_df


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


def main() -> None:
    st.title("Hanoi Real Estate Dashboard")

    active_only = st.sidebar.checkbox("Only active listings", value=True)
    base_df, table_df, correlation_df, region_stats_df = load_data(active_only=active_only)

    if base_df.empty:
        st.warning("No dashboard data found in the SQLite database yet.")
        return

    filtered_base, filtered_table, filtered_correlation, filtered_region_stats = apply_filters(
        base_df,
        table_df,
        correlation_df,
        region_stats_df,
    )

    render_overview(filtered_base, filtered_correlation, filtered_region_stats)

    tab_table, tab_correlation, tab_region = st.tabs(
        ["Table", "Distance vs Price/m²", "Regional Stats"]
    )
    with tab_table:
        render_table_tab(filtered_table)
    with tab_correlation:
        render_correlation_tab(filtered_correlation)
    with tab_region:
        render_region_stats_tab(filtered_region_stats)


def _range_from_series(series: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return 0.0, 1.0
    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if minimum == maximum:
        maximum = minimum + 1.0
    return minimum, maximum


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


if __name__ == "__main__":
    main()
