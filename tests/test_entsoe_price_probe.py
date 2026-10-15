import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nordic_current import prices
from scripts import test_entsoe_prices as probe


def valid_response() -> bytes:
    points = "\n".join(
        f"<Point><position>{position}</position><price.amount>"
        f"{'41.25' if position == 1 else '39.50' if position == 2 else '40.00'}"
        "</price.amount></Point>"
        for position in range(1, 25)
    )
    return f"""\
<Publication_MarketDocument>
  <TimeSeries>
    <in_Domain.mRID>10YNO-1--------2</in_Domain.mRID>
    <out_Domain.mRID>10YNO-1--------2</out_Domain.mRID>
    <currency_Unit.name>EUR</currency_Unit.name>
    <price_Measure_Unit.name>MWH</price_Measure_Unit.name>
    <Period>
      <timeInterval>
        <start>2024-01-01T00:00+01:00</start>
        <end>2024-01-02T00:00+01:00</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      {points}
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
""".encode("utf-8")


VALID_RESPONSE = valid_response()


class EntsoePriceProbeTests(unittest.TestCase):
    def test_parse_publication_summary(self):
        summary = prices.parse_response(VALID_RESPONSE)

        self.assertEqual(summary.period_start, "2023-12-31T23:00:00Z")
        self.assertEqual(summary.period_end, "2024-01-01T23:00:00Z")
        self.assertEqual(len(summary.rows), 24)
        self.assertEqual(summary.rows[0].timestamp.isoformat(), "2023-12-31T23:00:00+00:00")
        self.assertEqual(summary.rows[-1].timestamp.isoformat(), "2024-01-01T22:00:00+00:00")
        self.assertEqual(summary.rows[0].area, "NO1")
        self.assertEqual(str(summary.rows[0].price), "41.25")
        self.assertEqual(summary.rows[0].resolution, "PT60M")
        self.assertEqual(summary.rows[0].currency, "EUR")
        self.assertEqual(summary.rows[0].unit, "MWH")
        self.assertEqual(
            {
                (right.timestamp - left.timestamp).total_seconds()
                for left, right in zip(summary.rows, summary.rows[1:])
            },
            {3600},
        )

    def test_reject_period_without_timezone(self):
        response = VALID_RESPONSE.replace(
            b"2024-01-01T00:00+01:00",
            b"2024-01-01T00:00",
            1,
        )

        with self.assertRaisesRegex(ValueError, "without a timezone"):
            prices.parse_response(response)

    def test_reject_missing_observations(self):
        response = VALID_RESPONSE.replace(
            b"<Point><position>12</position><price.amount>40.00</price.amount></Point>",
            b"",
            1,
        )

        with self.assertRaisesRegex(ValueError, "missing observations"):
            prices.parse_response(response)

    def test_reject_malformed_and_non_price_responses(self):
        with self.assertRaisesRegex(ValueError, "not valid XML"):
            prices.parse_response(b"<not-closed>")
        with self.assertRaisesRegex(ValueError, "not an ENTSO-E price publication"):
            prices.parse_response(b"<Acknowledgement_MarketDocument />")

    def test_reject_duplicate_price_timestamps(self):
        response = VALID_RESPONSE.replace(
            b"<position>2</position>", b"<position>1</position>"
        )
        with self.assertRaisesRegex(ValueError, "duplicate observation times"):
            prices.parse_response(response)

    def test_reject_missing_unit_metadata(self):
        response = VALID_RESPONSE.replace(b"<currency_Unit.name>EUR</currency_Unit.name>", b"")
        response = response.replace(b"<price_Measure_Unit.name>MWH</price_Measure_Unit.name>", b"")

        with self.assertRaisesRegex(ValueError, "EUR/MWh"):
            prices.parse_response(response)

    def test_reject_response_for_a_different_bidding_zone(self):
        response = VALID_RESPONSE.replace(
            b"<out_Domain.mRID>10YNO-1--------2</out_Domain.mRID>",
            b"<out_Domain.mRID>10YNO-2--------T</out_Domain.mRID>",
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            prices.parse_response(response, "NO1")

    def test_reject_response_outside_requested_period(self):
        table = prices.parse_response(VALID_RESPONSE)
        wrong_period = prices.PriceTable(
            table.area,
            table.period_start,
            "2024-01-02T23:00:00Z",
            table.rows,
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            prices.validate_requested_window(
                wrong_period, date(2024, 1, 1), date(2024, 1, 1)
            )

    def test_validate_requested_window_matches_inclusive_norwegian_day(self):
        table = prices.parse_response(VALID_RESPONSE)

        prices.validate_requested_window(table, date(2024, 1, 1), date(2024, 1, 1))
        with self.assertRaisesRegex(ValueError, "does not match"):
            prices.validate_requested_window(
                table, date(2024, 1, 2), date(2024, 1, 2)
            )

    def test_validate_summer_boundary_offset(self):
        response = VALID_RESPONSE.replace(
            b"2024-01-01", b"2024-07-01"
        ).replace(b"2024-01-02", b"2024-07-02").replace(b"+01:00", b"+02:00")
        table = prices.parse_response(response)

        self.assertEqual(table.period_start, "2024-06-30T22:00:00Z")
        self.assertEqual(table.period_end, "2024-07-01T22:00:00Z")
        prices.validate_requested_window(table, date(2024, 7, 1), date(2024, 7, 1))

    def test_reject_unsupported_resolution(self):
        response = VALID_RESPONSE.replace(b"PT60M", b"PT60X")

        with self.assertRaisesRegex(ValueError, "unsupported time resolution"):
            prices.parse_response(response)

    def test_request_rejects_unsupported_zone_and_oversized_window(self):
        with self.assertRaisesRegex(ValueError, "Currently supported: NO1"):
            prices.request_prices(
                "test-token",
                "NO2",
                date(2024, 1, 1),
                date(2024, 1, 1),
            )
        with self.assertRaisesRegex(ValueError, "limited to 31"):
            prices.request_prices(
                "test-token",
                "NO1",
                date(2024, 1, 1),
                date(2024, 2, 1),
            )

    def test_http_error_is_sanitized_and_keeps_status_code(self):
        token = "sensitive-test-token"
        error = urllib.error.HTTPError(
            f"{prices.API_URL}?securityToken={token}", 401, "Unauthorized", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(prices.PriceDataError) as raised:
                prices.request_prices(
                    token, "NO1", date(2024, 1, 1), date(2024, 1, 1)
                )

        self.assertEqual(raised.exception.status_code, 401)
        self.assertNotIn(token, str(raised.exception))
        error.close()

    def test_fetch_persists_raw_response_metadata_and_normalized_csv(self):
        token = "sensitive-test-token"
        retrieved_at = datetime(2024, 1, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                prices, "request_prices", return_value=(200, VALID_RESPONSE)
            ) as request:
                table, metadata = prices.fetch_and_save_prices(
                    root,
                    token,
                    "NO1",
                    date(2024, 1, 1),
                    date(2024, 1, 1),
                    now=retrieved_at,
                )

            stem = "entsoe_prices_NO1_20240101_20240101"
            raw_path = root / "data/raw" / f"{stem}.xml"
            metadata_path = root / "data/raw" / f"{stem}.metadata.json"
            csv_path = root / "data/processed" / f"{stem}.csv"
            self.assertEqual(raw_path.read_bytes(), VALID_RESPONSE)
            saved_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_metadata["observation_count"], 24)
            self.assertEqual(saved_metadata["http_status"], 200)
            self.assertEqual(saved_metadata["returned_period_start"], table.period_start)
            self.assertEqual(saved_metadata["sha256"], metadata["sha256"])
            self.assertNotIn(token, metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(len(csv_path.read_text(encoding="utf-8").splitlines()), 25)
            request.assert_called_once_with(
                token, "NO1", date(2024, 1, 1), date(2024, 1, 1)
            )

    def test_dotenv_token_read_without_echoing(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text("ENTSOE_API_TOKEN='test-token-value'\n", encoding="utf-8")
            self.assertEqual(prices._read_dotenv_token(dotenv), "test-token-value")

    def test_authentication_error_does_not_echo_token(self):
        token = "sensitive-test-token"
        error = urllib.error.HTTPError(
            f"{prices.API_URL}?securityToken={token}", 401, "Unauthorized", {}, None
        )
        output = io.StringIO()
        with patch.dict(os.environ, {"ENTSOE_API_TOKEN": token}):
            with patch.object(probe, "request_prices", side_effect=error):
                with redirect_stderr(output):
                    result = probe.main()

        self.assertEqual(result, 1)
        self.assertIn("HTTP status: 401", output.getvalue())
        self.assertIn("Authentication failed", output.getvalue())
        self.assertNotIn(token, output.getvalue())
        error.close()

    def test_request_targets_one_day_of_no1_and_parses_response(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return VALID_RESPONSE

        token = "test-token-value"
        with patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            status, payload = prices.request_prices(
                token, "NO1", probe.START, probe.END
            )

        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.assertEqual(query["documentType"], ["A44"])
        self.assertEqual(query["in_Domain"], [prices.AREA_EICS["NO1"]])
        self.assertEqual(query["out_Domain"], [prices.AREA_EICS["NO1"]])
        self.assertEqual(query["periodStart"], ["202401010000"])
        self.assertEqual(query["periodEnd"], ["202401010000"])
        self.assertEqual(query["securityToken"], [token])
        self.assertEqual(status, 200)
        parsed = prices.parse_response(payload)
        self.assertEqual(len(parsed.rows), 24)
        self.assertEqual(parsed.period_start, "2023-12-31T23:00:00Z")
        self.assertEqual(parsed.period_end, "2024-01-01T23:00:00Z")
        prices.validate_requested_window(parsed, probe.START, probe.END)

    def test_missing_token_fails_clearly(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(probe, "PROJECT_ROOT", Path(tempfile.gettempdir())):
                with redirect_stderr(output):
                    result = probe.main()

        self.assertEqual(result, 1)
        self.assertIn("No ENTSOE_API_TOKEN found", output.getvalue())


if __name__ == "__main__":
    unittest.main()
