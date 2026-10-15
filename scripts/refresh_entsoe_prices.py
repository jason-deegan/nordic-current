"""Download and normalize a bounded ENTSO-E day-ahead price window."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nordic_current.prices import (  # noqa: E402
    AREA_EICS,
    PriceDataError,
    fetch_and_save_prices,
    load_token,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", choices=sorted(AREA_EICS), default="NO1")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()

    try:
        token = load_token(PROJECT_ROOT)
        if not token:
            print(
                "No ENTSOE_API_TOKEN found. Set it in the environment or project .env file.",
                file=sys.stderr,
            )
            return 1
        table, metadata = fetch_and_save_prices(
            PROJECT_ROOT,
            token,
            args.zone,
            args.start,
            args.end,
        )
    except PriceDataError as error:
        print(f"ENTSO-E price refresh failed: {error}", file=sys.stderr)
        return 1

    stem = f"entsoe_prices_{args.zone}_{args.start:%Y%m%d}_{args.end:%Y%m%d}"
    print(f"Source: ENTSO-E; observations: {len(table.rows)}")
    print(f"Returned period: {table.period_start} to {table.period_end}")
    print(f"Retrieved at: {metadata['retrieved_at']}")
    print(f"Raw response: {PROJECT_ROOT / 'data/raw' / f'{stem}.xml'}")
    print(f"Normalized table: {PROJECT_ROOT / 'data/processed' / f'{stem}.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
