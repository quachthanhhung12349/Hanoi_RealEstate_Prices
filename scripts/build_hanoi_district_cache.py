from __future__ import annotations

import argparse

from hanoi_real_estate.gis import HANOI_DISTRICTS_PATH, load_hanoi_districts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and cache Hanoi district polygons for GIS validation."
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore any existing district cache and rebuild it from remote geocoding.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    districts = load_hanoi_districts(
        force_refresh=args.force_refresh,
        allow_remote_fetch=True,
    )

    if districts.empty:
        print("No district polygons were cached.")
        print("This usually means remote geocoding returned no usable district boundaries.")
        return

    print(f"Cached {len(districts)} district polygons.")
    print(f"Cache file: {HANOI_DISTRICTS_PATH}")
    preview_columns = [column for column in ["district_name", "display_name"] if column in districts.columns]
    if preview_columns:
        print(districts[preview_columns].to_string(index=False))


if __name__ == "__main__":
    main()
