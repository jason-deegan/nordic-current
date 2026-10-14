"""Fetch, validate, cache, and inspect NVE reservoir-filling data."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

API_URL = (
    "https://biapi.nve.no/magasinstatistikk/api/"
    "Magasinstatistikk/HentOffentligData"
)
AREAS = {"NO1": 1, "NO2": 2, "NO3": 3, "NO4": 4, "NO5": 5}
CSV_COLUMNS = (
    "date",
    "area",
    "iso_year",
    "iso_week",
    "filling_fraction",
    "capacity_twh",
    "stored_twh",
    "previous_filling_fraction",
    "change_fraction",
)
RAW_PATH = Path("data/raw/nve_reservoirs.json")
METADATA_PATH = Path("data/raw/nve_reservoirs.metadata.json")
NORMALIZED_PATH = Path("data/processed/nve_reservoirs.csv")
REPORT_PATH = Path("reports/nve_reservoir_inspection.md")
MAX_FILLING_FRACTION = 1.1


class ReservoirDataError(ValueError):
    """Raised when an NVE response is unavailable or fails validation."""


@dataclass(frozen=True)
class ReservoirSnapshot:
    rows: tuple[dict[str, Any], ...]


def _number(record: dict[str, Any], key: str, index: int) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReservoirDataError(f"Record {index}: {key} must be numeric.")
    if not math.isfinite(float(value)):
        raise ReservoirDataError(f"Record {index}: {key} must be finite.")
    return float(value)


def normalize_payload(payload: bytes) -> ReservoirSnapshot:
    try:
        records = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReservoirDataError("NVE response is not valid UTF-8 JSON.") from None
    if not isinstance(records, list):
        raise ReservoirDataError("NVE response must be a JSON array.")

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    areas_seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ReservoirDataError(f"Record {index} must be a JSON object.")
        if record.get("omrType") != "EL":
            continue

        area_number = record.get("omrnr")
        if (
            isinstance(area_number, bool)
            or not isinstance(area_number, int)
            or area_number not in AREAS.values()
        ):
            raise ReservoirDataError(f"Record {index}: unexpected electricity area.")
        area = f"NO{area_number}"
        required = (
            "dato_Id",
            "iso_aar",
            "iso_uke",
            "fyllingsgrad",
            "kapasitet_TWh",
            "fylling_TWh",
            "fyllingsgrad_forrige_uke",
            "endring_fyllingsgrad",
        )
        missing_columns = [key for key in required if key not in record]
        if missing_columns:
            raise ReservoirDataError(
                f"Record {index}: missing required fields: {', '.join(missing_columns)}."
            )

        try:
            observed_date = date.fromisoformat(record["dato_Id"])
        except (TypeError, ValueError):
            raise ReservoirDataError(f"Record {index}: dato_Id must be an ISO date.") from None

        iso_year = record["iso_aar"]
        iso_week = record["iso_uke"]
        if (
            isinstance(iso_year, bool)
            or not isinstance(iso_year, int)
            or isinstance(iso_week, bool)
            or not isinstance(iso_week, int)
        ):
            raise ReservoirDataError(f"Record {index}: ISO year and week must be integers.")
        iso_calendar = observed_date.isocalendar()
        if (iso_calendar.year, iso_calendar.week) != (iso_year, iso_week):
            raise ReservoirDataError(f"Record {index}: ISO year/week do not match dato_Id.")

        key = (area, observed_date)
        if key in seen:
            raise ReservoirDataError(
                f"Duplicate reservoir record for {area} on {observed_date.isoformat()}."
            )
        seen.add(key)
        areas_seen.add(area)

        filling = _number(record, "fyllingsgrad", index)
        previous = _number(record, "fyllingsgrad_forrige_uke", index)
        capacity = _number(record, "kapasitet_TWh", index)
        stored = _number(record, "fylling_TWh", index)
        change = _number(record, "endring_fyllingsgrad", index)
        if not 0 <= filling <= MAX_FILLING_FRACTION:
            raise ReservoirDataError(
                f"Record {index}: fyllingsgrad must be a fraction from 0 to "
                f"{MAX_FILLING_FRACTION}, not a percentage."
            )
        if not 0 <= previous <= MAX_FILLING_FRACTION:
            raise ReservoirDataError(
                f"Record {index}: fyllingsgrad_forrige_uke must be a fraction."
            )
        if capacity <= 0 or stored < 0:
            raise ReservoirDataError(f"Record {index}: invalid capacity or stored volume.")

        normalized.append(
            {
                "date": observed_date.isoformat(),
                "area": area,
                "iso_year": iso_year,
                "iso_week": iso_week,
                "filling_fraction": filling,
                "capacity_twh": capacity,
                "stored_twh": stored,
                "previous_filling_fraction": previous,
                "change_fraction": change,
            }
        )

    if areas_seen != set(AREAS):
        missing_areas = sorted(set(AREAS) - areas_seen)
        raise ReservoirDataError(
            f"NVE response is missing expected electricity areas: {', '.join(missing_areas)}."
        )
    return ReservoirSnapshot(tuple(sorted(normalized, key=lambda row: (row["date"], row["area"]))))


def _write_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(contents)
    os.replace(temporary, path)


def _write_text(path: Path, contents: str) -> None:
    _write_bytes(path, contents.encode("utf-8"))


def _write_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    from io import StringIO

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _write_text(path, output.getvalue())


def _metadata_for(payload: bytes, retrieved_at: datetime) -> dict[str, Any]:
    return {
        "source": "NVE Magasinstatistikk API",
        "url": API_URL,
        "http_status": 200,
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _load_valid_cache(
    raw_path: Path,
    metadata_path: Path,
    max_age: timedelta,
    now: datetime,
) -> tuple[bytes, dict[str, Any]] | None:
    try:
        payload = raw_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        retrieved_at = datetime.fromisoformat(metadata["retrieved_at"])
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if hashlib.sha256(payload).hexdigest() != metadata.get("sha256"):
        return None
    age = now - retrieved_at.astimezone(timezone.utc)
    if age < timedelta(0) or age >= max_age:
        return None
    return payload, metadata


def _fetch_live() -> bytes:
    request = urllib.request.Request(API_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise ReservoirDataError(f"NVE API returned HTTP {response.status}.")
            return response.read()
    except urllib.error.HTTPError as error:
        raise ReservoirDataError(f"NVE API returned HTTP {error.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ReservoirDataError(
            f"NVE API request failed ({type(error).__name__})."
        ) from None


def render_inspection_report(
    snapshot: ReservoirSnapshot,
    metadata: dict[str, Any],
) -> str:
    rows = snapshot.rows
    by_area = {area: [row for row in rows if row["area"] == area] for area in AREAS}
    dates = [date.fromisoformat(row["date"]) for row in rows]
    retrieved_on = datetime.fromisoformat(metadata["retrieved_at"]).date().isoformat()
    lines = [
        f"# NVE reservoir data inspection — snapshot retrieved {retrieved_on}",
        "",
        "## Live observation snapshot",
        "",
        f"- Retrieved: `{metadata['retrieved_at']}`",
        f"- Source endpoint: [{metadata['url']}]({metadata['url']})",
        f"- HTTP status: {metadata['http_status']}",
        f"- SHA-256 of raw response: `{metadata['sha256']}`",
        f"- Normalized rows: {len(rows)}",
        f"- Coverage: {min(dates).isoformat()} to {max(dates).isoformat()}",
        "- Normalized fraction fields are ratios (for example, 0.75 means 75%), not percentages.",
        "- Missing values in the normalized required fields: 0 (validation rejects null or non-numeric values).",
        "",
        "| Area | Rows | First week | Last week | Missing weekly dates |",
        "|---|---:|---|---|---:|",
    ]
    total_gaps = 0
    for area, area_rows in by_area.items():
        area_dates = sorted(date.fromisoformat(row["date"]) for row in area_rows)
        expected_dates = {
            area_dates[0] + timedelta(days=7 * week)
            for week in range((area_dates[-1] - area_dates[0]).days // 7 + 1)
        }
        gaps = len(expected_dates - set(area_dates))
        irregular_intervals = sum(
            1
            for earlier, later in zip(area_dates, area_dates[1:])
            if (later - earlier).days % 7 != 0
        )
        total_gaps += gaps
        lines.append(
            f"| {area} | {len(area_rows)} | {area_dates[0].isoformat()} | "
            f"{area_dates[-1].isoformat()} | {gaps} |"
        )
        if irregular_intervals:
            lines.append(
                f"\nWarning: {area} has {irregular_intervals} interval(s) "
                "not divisible into seven-day weeks."
            )
    lines.extend(
        [
            "",
            f"Unique weeks with at least one area record: {len(set(dates))}. "
            f"Missing weekly area-dates within each area's span: {total_gaps}.",
            "Weekly-frequency check uses the observed calendar dates; this is not evidence "
            "that NVE's underlying measurements are error-free.",
            "",
            "## Source-documentation context (not live measurements)",
            "",
            "NVE describes the series as weekly filling statistics for its monitored major "
            "reservoir portfolio, grouped by electricity area (`EL`), national area (`NO`), "
            "and hydrological area (`VASS`). The OpenAPI schema gives filling fraction, "
            "capacity in TWh, and stored volume in TWh. NVE documentation identifies the "
            "data as NLOD, compatible with CC BY 3.0 Norway; attribution is required. "
            "This documentation context is separate from the live row counts above.",
            "",
        ]
    )
    return "\n".join(lines)


def refresh_reservoir_data(
    project_root: Path,
    *,
    force: bool = False,
    max_age: timedelta = timedelta(hours=24),
    now: datetime | None = None,
) -> tuple[ReservoirSnapshot, dict[str, Any], bool]:
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive.")
    root = project_root.resolve()
    raw_path = root / RAW_PATH
    metadata_path = root / METADATA_PATH
    normalized_path = root / NORMALIZED_PATH
    report_path = root / REPORT_PATH
    current_time = now or datetime.now(timezone.utc)

    cache = None if force else _load_valid_cache(
        raw_path, metadata_path, max_age, current_time
    )
    is_cached = cache is not None
    if cache:
        payload, metadata = cache
    else:
        payload = _fetch_live()
        metadata = _metadata_for(payload, current_time)

    snapshot = normalize_payload(payload)
    if not is_cached:
        _write_bytes(raw_path, payload)
        _write_text(
            metadata_path,
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        )
    _write_csv(normalized_path, snapshot.rows)
    _write_text(report_path, render_inspection_report(snapshot, metadata))
    return snapshot, metadata, is_cached
