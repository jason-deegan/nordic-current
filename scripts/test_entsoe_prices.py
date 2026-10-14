"""Make a one-day, read-only ENTSO-E day-ahead price request for NO1."""

from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

API_URL = "https://web-api.tp.entsoe.eu/api"
NO1_EIC = "10YNO-1--------2"
START = date(2024, 1, 1)
END = date(2024, 1, 2)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PriceObservation:
    area: str
    timestamp: datetime
    price: Decimal
    currency: str | None
    unit: str | None
    resolution: str


@dataclass(frozen=True)
class PriceTable:
    period_start: str
    period_end: str
    rows: tuple[PriceObservation, ...]


def _resolution_delta(value: str) -> timedelta:
    match = re.fullmatch(
        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        value,
    )
    if not match or not any(match.groups()):
        raise ValueError("The response contains an unsupported time resolution.")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if delta <= timedelta(0):
        raise ValueError("The response contains an unsupported time resolution.")
    return delta


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_dotenv_token(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError:
        raise ValueError("Could not read the local .env configuration file.") from None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != "ENTSOE_API_TOKEN":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip() or None
    return None


def load_token() -> str | None:
    token = os.environ.get("ENTSOE_API_TOKEN", "").strip()
    if token:
        return token
    return _read_dotenv_token(PROJECT_ROOT / ".env")


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("The response contains an invalid period timestamp.") from None


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_response(payload: bytes) -> PriceTable:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        raise ValueError("The response is not valid XML.") from None

    if _local_name(root.tag) != "Publication_MarketDocument":
        raise ValueError("The response is not an ENTSO-E price publication.")

    periods = [
        element
        for element in root.iter()
        if _local_name(element.tag) == "Period"
    ]
    if not periods:
        raise ValueError("The price publication contains no periods.")

    starts: list[datetime] = []
    ends: list[datetime] = []
    rows: list[PriceObservation] = []
    seen_timestamps: set[datetime] = set()

    for period in periods:
        interval = next(
            (element for element in period if _local_name(element.tag) == "timeInterval"),
            None,
        )
        if interval is None:
            raise ValueError("A price period is missing its time interval.")
        interval_values = {
            _local_name(child.tag): (child.text or "").strip() for child in interval
        }
        start = interval_values.get("start")
        end = interval_values.get("end")
        if not start or not end:
            raise ValueError("A price period is missing its start or end time.")
        period_start = _parse_timestamp(start)
        period_end = _parse_timestamp(end)
        if period_start >= period_end:
            raise ValueError("A price period has an invalid start/end interval.")
        starts.append(period_start)
        ends.append(period_end)

        resolution_element = next(
            (element for element in period if _local_name(element.tag) == "resolution"),
            None,
        )
        resolution = (resolution_element.text or "").strip() if resolution_element is not None else ""
        if not resolution:
            raise ValueError("A price period is missing its time resolution.")
        resolution_delta = _resolution_delta(resolution)
        series = next(
            (
                ancestor
                for ancestor in root.iter()
                if _local_name(ancestor.tag) == "TimeSeries" and period in list(ancestor.iter())
            ),
            None,
        )
        if series is None:
            raise ValueError("A price period is not associated with a time series.")
        series_metadata = {
            _local_name(child.tag): (child.text or "").strip()
            for child in series
            if len(child) == 0
        }
        currency = series_metadata.get("currency_Unit.name") or None
        unit = series_metadata.get("price_Measure_Unit.name") or None

        for point in period.iter():
            if _local_name(point.tag) != "Point":
                continue
            point_values = {
                _local_name(child.tag): (child.text or "").strip()
                for child in point.iter()
                if child is not point and len(child) == 0
            }
            if not point_values.get("position") or not point_values.get("price.amount"):
                raise ValueError("A price observation is missing its position or amount.")
            try:
                position = int(point_values["position"])
                amount = Decimal(point_values["price.amount"])
            except (ValueError, InvalidOperation):
                raise ValueError("A price observation contains a non-numeric value.") from None
            if position < 1 or not amount.is_finite():
                raise ValueError("A price observation contains an invalid position or amount.")
            timestamp = period_start + resolution_delta * (position - 1)
            if timestamp >= period_end:
                raise ValueError("A price observation falls outside its declared period.")
            if timestamp in seen_timestamps:
                raise ValueError("The price publication contains duplicate observation times.")
            seen_timestamps.add(timestamp)
            rows.append(
                PriceObservation(
                    area="NO1",
                    timestamp=timestamp,
                    price=amount,
                    currency=currency,
                    unit=unit,
                    resolution=resolution,
                )
            )

    if not rows:
        raise ValueError("The price publication contains no observations.")
    return PriceTable(
        period_start=_format_timestamp(min(starts)),
        period_end=_format_timestamp(max(ends)),
        rows=tuple(sorted(rows, key=lambda row: row.timestamp)),
    )


def request_prices(token: str) -> tuple[int, bytes]:
    params = {
        "documentType": "A44",
        "in_Domain": NO1_EIC,
        "out_Domain": NO1_EIC,
        "periodStart": START.strftime("%Y%m%d0000"),
        "periodEnd": END.strftime("%Y%m%d0000"),
        "securityToken": token,
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/xml"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read()


def _display(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "not stated in response"


def main() -> int:
    try:
        token = load_token()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    if not token:
        print(
            "No ENTSOE_API_TOKEN found. Set it in the environment or in the project .env file.",
            file=sys.stderr,
        )
        return 1

    try:
        status, payload = request_prices(token)
    except urllib.error.HTTPError as error:
        print(f"HTTP status: {error.code}", file=sys.stderr)
        if error.code in {401, 403}:
            print(
                "Authentication failed. Verify that the account is active and the API token is valid.",
                file=sys.stderr,
            )
        else:
            print("ENTSO-E rejected the request.", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(
            f"Request failed due to a network or I/O error ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(f"HTTP status: {status}")
    try:
        summary = parse_response(payload)
    except ValueError as error:
        print(f"Malformed or unexpected ENTSO-E response: {error}", file=sys.stderr)
        return 1

    print(f"Returned period: {summary.period_start} to {summary.period_end}")
    print(f"Observations: {len(summary.rows)}")
    print(f"Time resolution: {_display(tuple(sorted({row.resolution for row in summary.rows})))}")
    print(
        f"Currency: {_display(tuple(sorted({row.currency for row in summary.rows if row.currency})))}"
    )
    print(f"Price unit: {_display(tuple(sorted({row.unit for row in summary.rows if row.unit})))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
