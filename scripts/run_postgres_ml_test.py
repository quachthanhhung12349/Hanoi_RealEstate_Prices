from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from hanoi_real_estate.config import DATA_DIR, DATABASE_URL, DB_BACKEND
from hanoi_real_estate.features.accessibility_features import (
    DEFAULT_WALK_RADIUS_M,
    build_accessibility_feature_dataframe,
    write_accessibility_feature_outputs,
)
from hanoi_real_estate.features.ml_dataset import (
    DEFAULT_DISTRICT_MISMATCH_THRESHOLD_M,
    build_clean_ml_base_dataframe,
    write_ml_dataset_outputs,
)
from hanoi_real_estate.ml.price_model import train_xgboost_price_model, write_training_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full Phase 4 ML test pipeline against PostgreSQL/Supabase."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DATA_DIR / "ml" / "postgres_test"),
        help="Directory where PostgreSQL test datasets, reports, and model artifacts are written.",
    )
    parser.add_argument(
        "--mismatch-threshold-meters",
        type=float,
        default=DEFAULT_DISTRICT_MISMATCH_THRESHOLD_M,
        help="Discard coordinates farther than this from the listing's stated district.",
    )
    parser.add_argument(
        "--walk-radius-m",
        type=float,
        default=DEFAULT_WALK_RADIUS_M,
        help="Radius used for nearby POI counts.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Validation split size for model evaluation.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for the train/validation split.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive listings from PostgreSQL.",
    )
    parser.add_argument(
        "--keep-missing-coordinates",
        action="store_true",
        help="Keep rows without coordinates for later geocoding repair.",
    )
    parser.add_argument(
        "--no-snap",
        action="store_true",
        help="Do not snap small coordinate mismatches back to the stated district boundary.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if DB_BACKEND != "postgresql" or not DATABASE_URL:
        raise RuntimeError(
            "This test runner requires DATABASE_URL to be set so the repository uses PostgreSQL/Supabase."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_dir = output_dir / "model"

    base_path = output_dir / "hanoi_real_estate_ml_base.csv"
    discarded_path = output_dir / "hanoi_real_estate_ml_discarded.csv"
    base_summary_path = output_dir / "hanoi_real_estate_ml_summary.csv"
    accessibility_path = output_dir / "hanoi_real_estate_ml_accessibility.csv"
    accessibility_summary_path = output_dir / "hanoi_real_estate_ml_accessibility_summary.csv"

    print("Running PostgreSQL/Supabase ML test pipeline.")
    print(f"Output directory: {output_dir}")

    base_result = build_clean_ml_base_dataframe(
        active_only=not args.include_inactive,
        mismatch_threshold_meters=args.mismatch_threshold_meters,
        snap_to_stated_district=not args.no_snap,
        keep_missing_coordinates=args.keep_missing_coordinates,
    )
    write_ml_dataset_outputs(
        base_result,
        output_path=base_path,
        discarded_path=discarded_path,
        summary_path=base_summary_path,
    )
    print(f"Base rows: {len(base_result.cleaned):,}")
    print(f"Discarded rows: {len(base_result.discarded):,}")

    accessibility_result = build_accessibility_feature_dataframe(
        base_result.cleaned,
        walk_radius_m=args.walk_radius_m,
    )
    write_accessibility_feature_outputs(
        accessibility_result,
        output_path=accessibility_path,
        summary_path=accessibility_summary_path,
    )
    print(f"Accessibility rows: {len(accessibility_result.data):,}")

    model_artifacts = train_xgboost_price_model(
        pd.read_csv(accessibility_path, low_memory=False),
        test_size=args.test_size,
        random_state=args.random_state,
    )
    write_training_outputs(model_artifacts, output_dir=model_dir)
    print(f"Train rows: {model_artifacts.train_rows:,}")
    print(f"Validation rows: {model_artifacts.validation_rows:,}")
    print(model_artifacts.metrics.to_string(index=False))
    if not model_artifacts.district_metrics.empty:
        print("Top district rows by validation count:")
        print(model_artifacts.district_metrics.head(12).to_string(index=False))
    print(f"Model output directory: {model_dir}")


if __name__ == "__main__":
    main()

