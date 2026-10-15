"""Make a one-day, read-only ENTSO-E day-ahead price request for NO1."""

from __future__ import annotations

import sys
import urllib.error
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
START = date(2024, 1, 1)
END = date(2024, 1, 1)
AREA = "NO1"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nordic_current import prices  # noqa: E402
from nordic_current.prices import (  # noqa: E402
    PriceDataError,
    PriceTable,
    parse_response,
    request_prices,
    validate_requested_window,
)


def load_token() -> str | None:
    return prices.load_token(PROJECT_ROOT)


def main() -> int:
    try:
        token = load_token()
        if not token:
            print(
                "No ENTSOE_API_TOKEN found. Set it in the environment or project .env file.",
                file=sys.stderr,
            )
            return 1
        status, payload = request_prices(token, AREA, START, END)
        summary = parse_response(payload, AREA)
        validate_requested_window(summary, START, END)
    except urllib.error.HTTPError as error:
        print(f"HTTP status: {error.code}", file=sys.stderr)
        if error.code in {401, 403}:
            print("Authentication failed. Verify the local ENTSO-E token.", file=sys.stderr)
        else:
            print("ENTSO-E rejected the request.", file=sys.stderr)
        return 1
    except PriceDataError as error:
        if error.status_code is not None:
            print(f"HTTP status: {error.status_code}", file=sys.stderr)
            if error.status_code in {401, 403}:
                print(
                    "Authentication failed. Verify the local ENTSO-E token.",
                    file=sys.stderr,
                )
            else:
                print("ENTSO-E rejected the request.", file=sys.stderr)
        else:
            print(f"ENTSO-E probe failed: {error}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"Request failed ({type(error).__name__}).", file=sys.stderr)
        return 1

    print(f"HTTP status: {status}")
    _print_summary(summary)
    return 0


def _print_summary(summary: PriceTable) -> None:
    print(f"Returned period: {summary.period_start} to {summary.period_end}")
    print(f"Observations: {len(summary.rows)}")
    print(f"Time resolution: {', '.join(sorted({row.resolution for row in summary.rows}))}")
    print(f"Currency: {', '.join(sorted({row.currency for row in summary.rows}))}")
    print(f"Price unit: {', '.join(sorted({row.unit for row in summary.rows}))}")


if __name__ == "__main__":
    raise SystemExit(main())
