from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.preprocessing import FunctionTransformer
from xgboost import XGBRegressor


TARGET_COLUMN = "Giá/m² trị"
RANDOM_STATE = 42

NUMERIC_FEATURES = [
    "Diện tích trị",
    "Latitude",
    "Longitude",
    "dist_to_HN_center",
    "dist_nearest_university_m",
    "university_count_1000m",
    "dist_nearest_high_school_m",
    "high_school_count_1000m",
    "dist_nearest_hospital_m",
    "hospital_count_1000m",
    "dist_nearest_metro_station_m",
    "metro_station_count_1000m",
    "dist_nearest_bus_stop_m",
    "bus_stop_count_1000m",
    "dist_nearest_major_road_m",
    "major_road_count_1000m",
    "dist_nearest_ring_road_m",
    "ring_road_count_1000m",
]

CATEGORICAL_FEATURES = [
    "Huyện",
    "ward",
    "Số phòng ngủ",
    "Mặt tiền",
    "Đường vào",
    "Số tầng",
    "Số toilet",
    "Pháp lý",
]

MODEL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


@dataclass(frozen=True)
class TrainingArtifacts:
    model: Pipeline
    metrics: pd.DataFrame
    district_metrics: pd.DataFrame
    predictions: pd.DataFrame
    train_rows: int
    validation_rows: int


def train_xgboost_price_model(
    df: pd.DataFrame,
    *,
    test_size: float = 0.2,
    random_state: int = RANDOM_STATE,
) -> TrainingArtifacts:
    model_df = prepare_model_dataframe(df)
    train_df, validation_df = train_test_split(
        model_df,
        test_size=test_size,
        random_state=random_state,
    )

    model = build_xgboost_pipeline()
    model.fit(train_df[MODEL_FEATURES], train_df[TARGET_COLUMN])
    xgb_predictions = model.predict(validation_df[MODEL_FEATURES])
    interpolation_predictions = inverse_distance_weighted_predictions(
        train_df,
        validation_df,
    )

    metrics = pd.DataFrame(
        [
            _score_predictions(
                "xgboost_minimal_features",
                validation_df[TARGET_COLUMN].to_numpy(dtype=float),
                xgb_predictions,
            ),
            _score_predictions(
                "idw_interpolation_baseline",
                validation_df[TARGET_COLUMN].to_numpy(dtype=float),
                interpolation_predictions,
            ),
        ]
    )

    predictions = validation_df[
        [
            "Mã tin",
            "Huyện",
            "ward",
            "Latitude",
            "Longitude",
            TARGET_COLUMN,
        ]
    ].copy()
    predictions["xgboost_pred_price_m2"] = xgb_predictions
    predictions["idw_pred_price_m2"] = interpolation_predictions
    predictions["xgboost_abs_error"] = (predictions[TARGET_COLUMN] - predictions["xgboost_pred_price_m2"]).abs()
    predictions["idw_abs_error"] = (predictions[TARGET_COLUMN] - predictions["idw_pred_price_m2"]).abs()
    district_metrics = build_grouped_prediction_metrics(predictions, group_column="Huyện")

    return TrainingArtifacts(
        model=model,
        metrics=metrics,
        district_metrics=district_metrics,
        predictions=predictions.reset_index(drop=True),
        train_rows=len(train_df),
        validation_rows=len(validation_df),
    )


def prepare_model_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in [TARGET_COLUMN, *MODEL_FEATURES] if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required ML columns: {', '.join(missing)}")

    working = df[[TARGET_COLUMN, "Mã tin", *MODEL_FEATURES]].copy()
    for column in NUMERIC_FEATURES + [TARGET_COLUMN, "Latitude", "Longitude"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")

    working = working.dropna(subset=[TARGET_COLUMN, "Latitude", "Longitude"]).copy()
    working = working[working[TARGET_COLUMN] > 0].copy()
    return working.reset_index(drop=True)


def build_xgboost_pipeline() -> Pipeline:
    numeric_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
        ]
    )
    categorical_pipeline = Pipeline(
        steps=[
            ("stringify", FunctionTransformer(_stringify_categorical_frame, validate=False)),
            ("imputer", SimpleImputer(strategy="constant", fill_value="missing")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
        ]
    )
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, NUMERIC_FEATURES),
            ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
    )
    regressor = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=500,
        max_depth=4,
        learning_rate=0.04,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.5,
        min_child_weight=3,
        random_state=RANDOM_STATE,
        n_jobs=4,
    )
    return Pipeline(
        steps=[
            ("preprocess", preprocessor),
            ("model", regressor),
        ]
    )


def inverse_distance_weighted_predictions(
    train_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    *,
    k_neighbors: int = 10,
    power: float = 2.0,
    max_distance_m: float = 12_000.0,
) -> np.ndarray:
    train_coords = _latlon_to_web_mercator_m(
        train_df["Latitude"].to_numpy(dtype=float),
        train_df["Longitude"].to_numpy(dtype=float),
    )
    validation_coords = _latlon_to_web_mercator_m(
        validation_df["Latitude"].to_numpy(dtype=float),
        validation_df["Longitude"].to_numpy(dtype=float),
    )
    train_values = train_df[TARGET_COLUMN].to_numpy(dtype=float)
    fallback = float(np.nanmedian(train_values))

    predictions: list[float] = []
    for coord in validation_coords:
        distances = np.sqrt(((train_coords - coord) ** 2).sum(axis=1))
        if len(distances) == 0:
            predictions.append(fallback)
            continue

        nearest_count = min(k_neighbors, len(distances))
        nearest_idx = np.argpartition(distances, nearest_count - 1)[:nearest_count]
        nearest_distances = distances[nearest_idx]
        nearest_values = train_values[nearest_idx]
        within_range = nearest_distances <= max_distance_m
        if not within_range.any():
            predictions.append(fallback)
            continue

        nearest_distances = nearest_distances[within_range]
        nearest_values = nearest_values[within_range]
        weights = 1.0 / np.maximum(nearest_distances, 1.0) ** power
        predictions.append(float(np.average(nearest_values, weights=weights)))
    return np.array(predictions, dtype=float)


def write_training_outputs(
    artifacts: TrainingArtifacts,
    *,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts.metrics.to_csv(output_dir / "metrics.csv", index=False, encoding="utf-8-sig")
    artifacts.district_metrics.to_csv(output_dir / "district_metrics.csv", index=False, encoding="utf-8-sig")
    artifacts.predictions.to_csv(output_dir / "validation_predictions.csv", index=False, encoding="utf-8-sig")
    joblib.dump(artifacts.model, output_dir / "xgboost_price_per_m2_pipeline.joblib")

    metadata = {
        "target": TARGET_COLUMN,
        "features": MODEL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "train_rows": artifacts.train_rows,
        "validation_rows": artifacts.validation_rows,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_grouped_prediction_metrics(predictions: pd.DataFrame, *, group_column: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group_value, group in predictions.groupby(group_column, dropna=False):
        y_true = group[TARGET_COLUMN].to_numpy(dtype=float)
        xgb_pred = group["xgboost_pred_price_m2"].to_numpy(dtype=float)
        idw_pred = group["idw_pred_price_m2"].to_numpy(dtype=float)
        row: dict[str, Any] = {
            group_column: group_value,
            "rows": len(group),
            "actual_mean_price_m2": float(np.nanmean(y_true)),
            "actual_median_price_m2": float(np.nanmedian(y_true)),
        }
        row.update(_prefixed_score_fields("xgboost", y_true, xgb_pred))
        row.update(_prefixed_score_fields("idw", y_true, idw_pred))
        row["mae_delta_xgboost_minus_idw"] = row["xgboost_mae_million_vnd_m2"] - row["idw_mae_million_vnd_m2"]
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["rows", "xgboost_mae_million_vnd_m2"], ascending=[False, True])
        .reset_index(drop=True)
    )


def _prefixed_score_fields(prefix: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    score = _score_predictions(prefix, y_true, y_pred)
    return {
        f"{prefix}_mae_million_vnd_m2": score["mae_million_vnd_m2"],
        f"{prefix}_rmse_million_vnd_m2": score["rmse_million_vnd_m2"],
        f"{prefix}_mape_percent": score["mape_percent"],
        f"{prefix}_r2": score["r2"],
    }


def _score_predictions(model_name: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(y_true) & np.isfinite(y_pred)
    y_true = y_true[finite]
    y_pred = y_pred[finite]
    mae = mean_absolute_error(y_true, y_pred)
    rmse = math.sqrt(mean_squared_error(y_true, y_pred))
    mape = float(np.mean(np.abs((y_true - y_pred) / np.maximum(np.abs(y_true), 1e-9))) * 100)
    return {
        "model": model_name,
        "rows": len(y_true),
        "mae_million_vnd_m2": mae,
        "rmse_million_vnd_m2": rmse,
        "mape_percent": mape,
        "r2": r2_score(y_true, y_pred),
    }


def _latlon_to_web_mercator_m(latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    latitudes = np.clip(latitudes, -85.05112878, 85.05112878)
    radius = 6_378_137.0
    x = radius * np.radians(longitudes)
    y = radius * np.log(np.tan(np.pi / 4.0 + np.radians(latitudes) / 2.0))
    return np.column_stack([x, y])


def _stringify_categorical_frame(values: Any) -> Any:
    frame = pd.DataFrame(values).copy()
    return frame.map(lambda value: "missing" if pd.isna(value) else str(value))
