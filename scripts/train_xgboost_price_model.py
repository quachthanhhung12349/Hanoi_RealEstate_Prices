from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from hanoi_real_estate.config import DATA_DIR
from hanoi_real_estate.ml.price_model import (
    MODEL_FEATURES,
    TARGET_COLUMN,
    train_xgboost_price_model,
    write_training_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a minimal XGBoost price-per-m2 model and compare it to IDW interpolation."
    )
    parser.add_argument(
        "--input-path",
        default=str(DATA_DIR / "ml" / "hanoi_real_estate_ml_accessibility.csv"),
        help="Accessibility-enriched ML dataset.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DATA_DIR / "ml" / "model"),
        help="Directory for model artifact, metrics, metadata, and validation predictions.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Validation split size. Default is 0.2 for 80/20 train/validation.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for reproducible train/validation split.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    if not input_path.exists():
        raise FileNotFoundError(
            f"Missing ML dataset: {input_path}. Run scripts/build_ml_accessibility_features.py first."
        )

    df = pd.read_csv(input_path, low_memory=False)
    artifacts = train_xgboost_price_model(
        df,
        test_size=args.test_size,
        random_state=args.random_state,
    )
    write_training_outputs(artifacts, output_dir=Path(args.output_dir))

    print("Trained XGBoost price-per-m2 model.")
    print(f"Target: {TARGET_COLUMN}")
    print(f"Features: {len(MODEL_FEATURES)}")
    print(f"Train rows: {artifacts.train_rows:,}")
    print(f"Validation rows: {artifacts.validation_rows:,}")
    print(artifacts.metrics.to_string(index=False))
    print(f"Output directory: {args.output_dir}")


if __name__ == "__main__":
    main()

