from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from hanoi_real_estate.config import ROOT_DIR


DEFAULT_SOURCE = ROOT_DIR / "data" / "ml" / "postgres_test" / "model" / "xgboost_price_per_m2_pipeline.joblib"
DEFAULT_OUTPUT = ROOT_DIR / "models" / "xgboost_price_per_m2_pipeline.joblib"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy a trained price model artifact into the Streamlit deployment model path."
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Trained model artifact to export.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Deployment model artifact path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if not source.exists():
        raise FileNotFoundError(f"Model artifact not found: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    print(f"Exported model artifact: {output}")


if __name__ == "__main__":
    main()

