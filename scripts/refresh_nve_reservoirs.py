"""Refresh the cached NVE weekly reservoir dataset and inspection report."""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nordic_current.reservoirs import (  # noqa: E402
    ReservoirDataError,
    refresh_reservoir_data,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch a fresh response even if the local cache is under 24 hours old.",
    )
    args = parser.parse_args()
    try:
        snapshot, metadata, cached = refresh_reservoir_data(
            PROJECT_ROOT,
            force=args.force,
            max_age=timedelta(hours=24),
        )
    except (ReservoirDataError, ValueError) as error:
        print(f"Reservoir refresh failed: {error}", file=sys.stderr)
        return 1

    status = "cache" if cached else "live fetch"
    print(f"Source: {status}; records: {len(snapshot.rows)}")
    print(f"Retrieved at: {metadata['retrieved_at']}")
    print(f"Normalized table: {PROJECT_ROOT / 'data/processed/nve_reservoirs.csv'}")
    print(f"Inspection report: {PROJECT_ROOT / 'reports/nve_reservoir_inspection.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
