from __future__ import annotations

import argparse

from hanoi_real_estate.features.accessibility_sources import (
    ACCESSIBILITY_LAYER_FILES,
    build_accessibility_gis_cache,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and cache Hanoi accessibility GIS layers for Phase 4 ML features."
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Fetch layers again even if cached GeoJSON files already exist.",
    )
    parser.add_argument(
        "--layer",
        choices=sorted(ACCESSIBILITY_LAYER_FILES),
        action="append",
        dest="layers",
        help="Specific layer to build. Repeat to build multiple layers. Defaults to all layers.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = build_accessibility_gis_cache(
        layers=args.layers,
        force_refresh=args.force_refresh,
    )

    print("Built accessibility GIS cache.")
    for result in results:
        print(
            f"{result.layer}: {result.row_count:,} rows "
            f"({result.status}, {result.source}) -> {result.path}"
        )


if __name__ == "__main__":
    main()

