"""Retrieve, validate, and store Norwegian day-ahead price data."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any

API_URL = "https://web-api.tp.entsoe.eu/api"
AREA_EICS = {"NO1": "10YNO-1--------2"}
MAX_REQUEST_DAYS = 31
# The live-tested NO1 date boundaries use Norway's CET/CEST UTC offsets.
UTC_OFFSETS = (timedelta(hours=1), timedelta(hours=2))
CSV_COLUMNS = ("area", "timestamp_utc", "price", "currency", "unit", "resolution")


class PriceDataError(ValueError):
    """Raised when an ENTSO-E response cannot be retrieved or validated."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PriceObservation:
    area: str
    timestamp: datetime
    price: Decimal
    currency: str
    unit: str
    resolution: str


@dataclass(frozen=True)
class PriceTable:
    area: str
    period_start: str
    period_end: str
    rows: tuple[PriceObservation, ...]


def _validate_request(area: str, start_date: date, end_date: date) -> str:
    eic = _eic_for_area(area)
    if type(start_date) is not date or type(end_date) is not date:
        raise PriceDataError("Request boundaries must be calendar dates.")
    if start_date > end_date:
        raise PriceDataError("Request start date must not be after its end date.")
    if end_date == date.max:
        raise PriceDataError("Request end date is too late to form an exclusive boundary.")
    request_days = (end_date - start_date).days + 1
    if request_days > MAX_REQUEST_DAYS:
        raise PriceDataError(
            f"Requests are limited to {MAX_REQUEST_DAYS} inclusive calendar dates."
        )
    return eic


def _eic_for_area(area: str) -> str:
    try:
        return AREA_EICS[area]
    except KeyError:
        raise PriceDataError(
            f"Unsupported bidding zone: {area}. Currently supported: NO1."
        ) from None


def _resolution_delta(value: str) -> timedelta:
    match = re.fullmatch(
        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        value,
    )
    if not match or not any(match.groups()):
        raise PriceDataError("The response contains an unsupported time resolution.")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if delta <= timedelta(0):
        raise PriceDataError("The response contains an unsupported time resolution.")
    return delta


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError:
        raise PriceDataError("The response contains an invalid period timestamp.") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise PriceDataError("The response contains a period timestamp without a timezone.")
    return timestamp.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_response(payload: bytes, area: str = "NO1") -> PriceTable:
    eic = _eic_for_area(area)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        raise PriceDataError("The response is not valid XML.") from None
    if _local_name(root.tag) != "Publication_MarketDocument":
        raise PriceDataError("The response is not an ENTSO-E price publication.")

    rows: list[PriceObservation] = []
    intervals: list[tuple[datetime, datetime]] = []
    seen_timestamps: set[datetime] = set()
    for series in root.iter():
        if _local_name(series.tag) != "TimeSeries":
            continue
        series_metadata = {
            _local_name(child.tag): (child.text or "").strip()
            for child in series
            if len(child) == 0
        }
        if (
            series_metadata.get("in_Domain.mRID") != eic
            or series_metadata.get("out_Domain.mRID") != eic
        ):
            raise PriceDataError("The response bidding zone does not match the request.")
        currency = series_metadata.get("currency_Unit.name")
        unit = series_metadata.get("price_Measure_Unit.name")
        if currency != "EUR" or unit != "MWH":
            raise PriceDataError("The response must declare prices in EUR/MWh.")

        periods = [
            element
            for element in series.iter()
            if _local_name(element.tag) == "Period"
        ]
        for period in periods:
            interval = next(
                (element for element in period if _local_name(element.tag) == "timeInterval"),
                None,
            )
            if interval is None:
                raise PriceDataError("A price period is missing its time interval.")
            interval_values = {
                _local_name(child.tag): (child.text or "").strip() for child in interval
            }
            start = interval_values.get("start")
            end = interval_values.get("end")
            if not start or not end:
                raise PriceDataError("A price period is missing its start or end time.")
            period_start = _parse_timestamp(start)
            period_end = _parse_timestamp(end)
            if period_start >= period_end:
                raise PriceDataError("A price period has an invalid start/end interval.")
            intervals.append((period_start, period_end))

            resolution_element = next(
                (element for element in period if _local_name(element.tag) == "resolution"),
                None,
            )
            resolution = (
                (resolution_element.text or "").strip()
                if resolution_element is not None
                else ""
            )
            if not resolution:
                raise PriceDataError("A price period is missing its time resolution.")
            resolution_delta = _resolution_delta(resolution)
            interval_seconds = (period_end - period_start).total_seconds()
            resolution_seconds = resolution_delta.total_seconds()
            if interval_seconds % resolution_seconds:
                raise PriceDataError(
                    "A price period is not evenly divisible by its resolution."
                )
            expected_positions = int(interval_seconds // resolution_seconds)
            positions: set[int] = set()

            for point in period.iter():
                if _local_name(point.tag) != "Point":
                    continue
                point_values = {
                    _local_name(child.tag): (child.text or "").strip()
                    for child in point.iter()
                    if child is not point and len(child) == 0
                }
                if not point_values.get("position") or not point_values.get("price.amount"):
                    raise PriceDataError(
                        "A price observation is missing its position or amount."
                    )
                try:
                    position = int(point_values["position"])
                    amount = Decimal(point_values["price.amount"])
                except (ValueError, InvalidOperation):
                    raise PriceDataError(
                        "A price observation contains a non-numeric value."
                    ) from None
                if position < 1 or not amount.is_finite():
                    raise PriceDataError(
                        "A price observation contains an invalid position or amount."
                    )
                positions.add(position)
                timestamp = period_start + resolution_delta * (position - 1)
                if timestamp >= period_end:
                    raise PriceDataError(
                        "A price observation falls outside its declared period."
                    )
                if timestamp in seen_timestamps:
                    raise PriceDataError(
                        "The price publication contains duplicate observation times."
                    )
                seen_timestamps.add(timestamp)
                rows.append(
                    PriceObservation(
                        area=area,
                        timestamp=timestamp,
                        price=amount,
                        currency=currency,
                        unit=unit,
                        resolution=resolution,
                    )
                )
            if positions != set(range(1, expected_positions + 1)):
                raise PriceDataError("A price period contains missing observations.")

    if not rows:
        raise PriceDataError("The price publication contains no observations.")
    ordered_intervals = sorted(intervals)
    if any(
        earlier_end != later_start
        for (_, earlier_end), (later_start, _) in zip(
            ordered_intervals, ordered_intervals[1:]
        )
    ):
        raise PriceDataError("The price publication contains gaps or overlapping periods.")
    return PriceTable(
        area=area,
        period_start=_format_timestamp(ordered_intervals[0][0]),
        period_end=_format_timestamp(ordered_intervals[-1][1]),
        rows=tuple(sorted(rows, key=lambda row: row.timestamp)),
    )


def validate_requested_window(
    table: PriceTable,
    start_date: date,
    end_date: date,
) -> None:
    _validate_request(table.area, start_date, end_date)
    expected_start = datetime.combine(start_date, time.min, timezone.utc)
    expected_end = datetime.combine(end_date + timedelta(days=1), time.min, timezone.utc)
    actual_start = datetime.fromisoformat(table.period_start.replace("Z", "+00:00"))
    actual_end = datetime.fromisoformat(table.period_end.replace("Z", "+00:00"))
    possible_starts = {expected_start - offset for offset in UTC_OFFSETS}
    possible_ends = {expected_end - offset for offset in UTC_OFFSETS}
    if actual_start not in possible_starts or actual_end not in possible_ends:
        raise PriceDataError(
            "The returned UTC period does not match the requested Norwegian market dates."
        )


def request_prices(
    token: str,
    area: str,
    start_date: date,
    end_date: date,
) -> tuple[int, bytes]:
    eic = _validate_request(area, start_date, end_date)
    if not isinstance(token, str) or not token.strip():
        raise PriceDataError("An ENTSO-E token is required.")
    parameters = {
        "documentType": "A44",
        "in_Domain": eic,
        "out_Domain": eic,
        "periodStart": start_date.strftime("%Y%m%d0000"),
        "periodEnd": end_date.strftime("%Y%m%d0000"),
        "securityToken": token,
    }
    url = f"{API_URL}?{urllib.parse.urlencode(parameters)}"
    request = urllib.request.Request(url, headers={"Accept": "application/xml"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise PriceDataError(f"ENTSO-E API returned HTTP {response.status}.")
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        raise PriceDataError(
            f"ENTSO-E API returned HTTP {error.code}.",
            status_code=error.code,
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PriceDataError(
            f"ENTSO-E API request failed ({type(error).__name__})."
        ) from None


def _read_dotenv_token(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError:
        raise PriceDataError("Could not read the local .env configuration file.") from None

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


def load_token(project_root: Path) -> str | None:
    token = os.environ.get("ENTSOE_API_TOKEN", "").strip()
    if token:
        return token
    return _read_dotenv_token(project_root / ".env")


def _metadata_for(
    payload: bytes,
    http_status: int,
    table: PriceTable,
    start_date: date,
    end_date: date,
    retrieved_at: datetime,
) -> dict[str, Any]:
    return {
        "source": "ENTSO-E Transparency Platform",
        "url": API_URL,
        "http_status": http_status,
        "area": table.area,
        "eic": AREA_EICS[table.area],
        "requested_start_date": start_date.isoformat(),
        "requested_end_date": end_date.isoformat(),
        "returned_period_start": table.period_start,
        "returned_period_end": table.period_end,
        "observation_count": len(table.rows),
        "resolutions": sorted({row.resolution for row in table.rows}),
        "currency": table.rows[0].currency,
        "unit": table.rows[0].unit,
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(contents)
    os.replace(temporary, path)


def _write_text(path: Path, contents: str) -> None:
    _write_bytes(path, contents.encode("utf-8"))


def _write_csv(path: Path, rows: tuple[PriceObservation, ...]) -> None:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "area": row.area,
                "timestamp_utc": _format_timestamp(row.timestamp),
                "price": str(row.price),
                "currency": row.currency,
                "unit": row.unit,
                "resolution": row.resolution,
            }
        )
    _write_text(path, output.getvalue())


def fetch_and_save_prices(
    project_root: Path,
    token: str,
    area: str,
    start_date: date,
    end_date: date,
    *,
    now: datetime | None = None,
) -> tuple[PriceTable, dict[str, Any]]:
    _validate_request(area, start_date, end_date)
    status, payload = request_prices(token, area, start_date, end_date)
    table = parse_response(payload, area)
    validate_requested_window(table, start_date, end_date)
    metadata = _metadata_for(
        payload,
        status,
        table,
        start_date,
        end_date,
        now or datetime.now(timezone.utc),
    )
    stem = f"entsoe_prices_{area}_{start_date:%Y%m%d}_{end_date:%Y%m%d}"
    root = project_root.resolve()
    _write_bytes(root / "data/raw" / f"{stem}.xml", payload)
    _write_text(
        root / "data/raw" / f"{stem}.metadata.json",
        json.dumps(metadata, indent=2) + "\n",
    )
    _write_csv(root / "data/processed" / f"{stem}.csv", table.rows)
    return table, metadata
