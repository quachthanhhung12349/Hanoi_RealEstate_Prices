from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from hanoi_real_estate.config import DATA_DIR
from hanoi_real_estate.features.accessibility_features import (
    DEFAULT_WALK_RADIUS_M,
    FEATURE_PREFIX_BY_LAYER,
    build_accessibility_feature_dataframe,
    write_accessibility_feature_outputs,
)
from hanoi_real_estate.features.accessibility_sources import ACCESSIBILITY_LAYER_FILES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add nearest-POI distance and 1km POI-count features to the ML base dataset."
    )
    parser.add_argument(
        "--input-path",
        default=str(DATA_DIR / "ml" / "hanoi_real_estate_ml_base.csv"),
        help="Cleaned ML base CSV from scripts/build_ml_training_dataset.py.",
    )
    parser.add_argument(
        "--output-path",
        default=str(DATA_DIR / "ml" / "hanoi_real_estate_ml_accessibility.csv"),
        help="Output CSV with accessibility features appended.",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DATA_DIR / "ml" / "hanoi_real_estate_ml_accessibility_summary.csv"),
        help="Output CSV with feature-build summary metrics.",
    )
    parser.add_argument(
        "--walk-radius-m",
        type=float,
        default=DEFAULT_WALK_RADIUS_M,
        help="Radius used for on-foot POI counts.",
    )
    parser.add_argument(
        "--layer",
        choices=sorted(ACCESSIBILITY_LAYER_FILES),
        action="append",
        dest="layers",
        help="Specific accessibility layer to use. Repeat to use multiple layers. Defaults to all layers.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    if not input_path.exists():
        raise FileNotFoundError(
            f"Missing ML base dataset: {input_path}. Run scripts/build_ml_training_dataset.py first."
        )

    listings_df = pd.read_csv(input_path, low_memory=False)
    result = build_accessibility_feature_dataframe(
        listings_df,
        layers=args.layers,
        walk_radius_m=args.walk_radius_m,
    )
    write_accessibility_feature_outputs(
        result,
        output_path=Path(args.output_path),
        summary_path=Path(args.summary_path) if args.summary_path else None,
    )

    print("Built ML accessibility feature dataset.")
    print(f"Input rows: {len(listings_df):,}")
    print(f"Output rows: {len(result.data):,}")
    print(f"POI layers: {', '.join(args.layers or FEATURE_PREFIX_BY_LAYER)}")
    print(result.summary.to_string(index=False))
    print(f"Output: {args.output_path}")
    if args.summary_path:
        print(f"Summary: {args.summary_path}")


if __name__ == "__main__":
    main()

