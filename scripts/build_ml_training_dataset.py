from __future__ import annotations

import argparse
from pathlib import Path

from hanoi_real_estate.config import DATA_DIR
from hanoi_real_estate.features.ml_dataset import (
    DEFAULT_DISTRICT_MISMATCH_THRESHOLD_M,
    build_clean_ml_base_dataframe,
    write_ml_dataset_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a district-validated base dataset for Phase 4 ML feature engineering."
    )
    parser.add_argument(
        "--output-path",
        default=str(DATA_DIR / "ml" / "hanoi_real_estate_ml_base.csv"),
        help="CSV path for cleaned rows that are ready for GIS feature enrichment.",
    )
    parser.add_argument(
        "--discarded-path",
        default=str(DATA_DIR / "ml" / "hanoi_real_estate_ml_discarded.csv"),
        help="CSV path for rows removed during cleaning.",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DATA_DIR / "ml" / "hanoi_real_estate_ml_summary.csv"),
        help="CSV path for cleaning counts and audit metrics.",
    )
    parser.add_argument(
        "--mismatch-threshold-meters",
        type=float,
        default=DEFAULT_DISTRICT_MISMATCH_THRESHOLD_M,
        help="Discard coordinates farther than this from the listing's stated district.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive listings from the source database.",
    )
    parser.add_argument(
        "--keep-missing-coordinates",
        action="store_true",
        help="Keep rows without coordinates for a later geocoding repair pass.",
    )
    parser.add_argument(
        "--no-snap",
        action="store_true",
        help="Do not snap small coordinate mismatches back to the stated district boundary.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_clean_ml_base_dataframe(
        active_only=not args.include_inactive,
        mismatch_threshold_meters=args.mismatch_threshold_meters,
        snap_to_stated_district=not args.no_snap,
        keep_missing_coordinates=args.keep_missing_coordinates,
    )
    write_ml_dataset_outputs(
        result,
        output_path=Path(args.output_path),
        discarded_path=Path(args.discarded_path) if args.discarded_path else None,
        summary_path=Path(args.summary_path) if args.summary_path else None,
    )

    print("Built ML base dataset.")
    print(f"Cleaned rows: {len(result.cleaned):,}")
    print(f"Discarded rows: {len(result.discarded):,}")
    if not result.summary.empty:
        print(result.summary.to_string(index=False))
    print(f"Output: {args.output_path}")
    if args.discarded_path:
        print(f"Discarded report: {args.discarded_path}")
    if args.summary_path:
        print(f"Summary: {args.summary_path}")


if __name__ == "__main__":
    main()

