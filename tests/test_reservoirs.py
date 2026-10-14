import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from nordic_current import reservoirs


def sample_records():
    records = []
    for area_number in reservoirs.AREAS.values():
        records.append(
            {
                "dato_Id": "2024-01-07",
                "omrType": "EL",
                "omrnr": area_number,
                "iso_aar": 2024,
                "iso_uke": 1,
                "fyllingsgrad": 0.75,
                "kapasitet_TWh": 10.0,
                "fylling_TWh": 7.5,
                "fyllingsgrad_forrige_uke": 0.74,
                "endring_fyllingsgrad": 0.01,
            }
        )
    return records


def payload_for(records):
    return json.dumps(records).encode("utf-8")


class ReservoirNormalizationTests(unittest.TestCase):
    def test_normalizes_expected_areas_and_fraction_units(self):
        snapshot = reservoirs.normalize_payload(payload_for(sample_records()))

        self.assertEqual(len(snapshot.rows), 5)
        self.assertEqual({row["area"] for row in snapshot.rows}, set(reservoirs.AREAS))
        self.assertEqual(snapshot.rows[0]["date"], "2024-01-07")
        self.assertEqual(snapshot.rows[0]["filling_fraction"], 0.75)
        self.assertNotIn("filling_percent", snapshot.rows[0])

    def test_allows_documented_slightly_over_full_fraction(self):
        records = sample_records()
        records[0]["fyllingsgrad"] = 1.02
        snapshot = reservoirs.normalize_payload(payload_for(records))

        self.assertEqual(snapshot.rows[0]["filling_fraction"], 1.02)

    def test_rejects_percent_encoded_filling(self):
        records = sample_records()
        records[0]["fyllingsgrad"] = 75.0

        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "not a percentage"):
            reservoirs.normalize_payload(payload_for(records))

    def test_rejects_missing_area_or_required_column(self):
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "missing expected"):
            reservoirs.normalize_payload(payload_for(sample_records()[:-1]))

        records = sample_records()
        del records[0]["kapasitet_TWh"]
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "missing required fields"):
            reservoirs.normalize_payload(payload_for(records))

    def test_rejects_invalid_date_duplicates_missing_and_wrong_types(self):
        records = sample_records()
        records[0]["dato_Id"] = "not-a-date"
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "ISO date"):
            reservoirs.normalize_payload(payload_for(records))

        records = sample_records()
        records.append(records[0].copy())
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "Duplicate"):
            reservoirs.normalize_payload(payload_for(records))

        records = sample_records()
        records[0]["fyllingsgrad"] = None
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "must be numeric"):
            reservoirs.normalize_payload(payload_for(records))

        records = sample_records()
        records[0]["iso_uke"] = True
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "must be integers"):
            reservoirs.normalize_payload(payload_for(records))

    def test_rejects_inconsistent_iso_week_and_invalid_capacity(self):
        records = sample_records()
        records[0]["iso_uke"] = 2
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "do not match"):
            reservoirs.normalize_payload(payload_for(records))

        records = sample_records()
        records[0]["kapasitet_TWh"] = 0
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "capacity"):
            reservoirs.normalize_payload(payload_for(records))

    def test_rejects_non_array_or_invalid_json(self):
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "not valid"):
            reservoirs.normalize_payload(b"{")
        with self.assertRaisesRegex(reservoirs.ReservoirDataError, "JSON array"):
            reservoirs.normalize_payload(b'{"unexpected": true}')


class ReservoirCacheTests(unittest.TestCase):
    def test_refresh_writes_raw_metadata_normalized_table_and_report(self):
        payload = payload_for(sample_records())
        retrieved_at = datetime(2024, 1, 8, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(reservoirs, "_fetch_live", return_value=payload) as fetch:
                snapshot, metadata, cached = reservoirs.refresh_reservoir_data(
                    root, now=retrieved_at
                )
            self.assertFalse(cached)
            fetch.assert_called_once()
            self.assertEqual(len(snapshot.rows), 5)
            self.assertEqual(
                (root / reservoirs.RAW_PATH).read_bytes(),
                payload,
            )
            self.assertTrue((root / reservoirs.METADATA_PATH).is_file())
            csv_text = (root / reservoirs.NORMALIZED_PATH).read_text(encoding="utf-8")
            self.assertIn("filling_fraction", csv_text.splitlines()[0])
            self.assertEqual(len(csv_text.splitlines()), 6)
            report = (root / reservoirs.REPORT_PATH).read_text(encoding="utf-8")
            self.assertIn("# NVE reservoir data inspection — snapshot retrieved 2024-01-08", report)
            self.assertIn("Live observation snapshot", report)
            self.assertIn("Source-documentation context", report)
            self.assertEqual(metadata["http_status"], 200)

    def test_fresh_verified_cache_prevents_another_request(self):
        payload = payload_for(sample_records())
        now = datetime(2024, 1, 8, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(reservoirs, "_fetch_live", return_value=payload):
                reservoirs.refresh_reservoir_data(root, now=now)
            with patch.object(reservoirs, "_fetch_live") as fetch:
                _, _, cached = reservoirs.refresh_reservoir_data(
                    root, now=now + timedelta(hours=1)
                )
            self.assertTrue(cached)
            fetch.assert_not_called()

    def test_corrupt_cache_triggers_fetch(self):
        payload = payload_for(sample_records())
        now = datetime(2024, 1, 8, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(reservoirs, "_fetch_live", return_value=payload):
                reservoirs.refresh_reservoir_data(root, now=now)
            (root / reservoirs.RAW_PATH).write_text("tampered", encoding="utf-8")
            with patch.object(reservoirs, "_fetch_live", return_value=payload) as fetch:
                _, _, cached = reservoirs.refresh_reservoir_data(
                    root, now=now + timedelta(hours=1)
                )
            self.assertFalse(cached)
            fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
