import io
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scripts import test_entsoe_prices as probe


VALID_RESPONSE = b"""\
<Publication_MarketDocument>
  <TimeSeries>
    <currency_Unit.name>EUR</currency_Unit.name>
    <price_Measure_Unit.name>MWH</price_Measure_Unit.name>
    <Period>
      <timeInterval>
        <start>2024-01-01T00:00Z</start>
        <end>2024-01-02T00:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>41.25</price.amount></Point>
      <Point><position>2</position><price.amount>39.50</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""


class EntsoePriceProbeTests(unittest.TestCase):
    def test_parse_publication_summary(self):
        summary = probe.parse_response(VALID_RESPONSE)

        self.assertEqual(summary.period_start, "2024-01-01T00:00:00Z")
        self.assertEqual(summary.period_end, "2024-01-02T00:00:00Z")
        self.assertEqual(len(summary.rows), 2)
        self.assertEqual(summary.rows[0].timestamp.isoformat(), "2024-01-01T00:00:00+00:00")
        self.assertEqual(summary.rows[0].area, "NO1")
        self.assertEqual(str(summary.rows[0].price), "41.25")
        self.assertEqual(summary.rows[0].resolution, "PT60M")
        self.assertEqual(summary.rows[0].currency, "EUR")
        self.assertEqual(summary.rows[0].unit, "MWH")

    def test_reject_malformed_and_non_price_responses(self):
        with self.assertRaisesRegex(ValueError, "not valid XML"):
            probe.parse_response(b"<not-closed>")
        with self.assertRaisesRegex(ValueError, "not an ENTSO-E price publication"):
            probe.parse_response(b"<Acknowledgement_MarketDocument />")

    def test_reject_duplicate_price_timestamps(self):
        response = VALID_RESPONSE.replace(
            b"<position>2</position>", b"<position>1</position>"
        )
        with self.assertRaisesRegex(ValueError, "duplicate observation times"):
            probe.parse_response(response)

    def test_missing_unit_metadata_is_not_invented(self):
        response = VALID_RESPONSE.replace(b"<currency_Unit.name>EUR</currency_Unit.name>", b"")
        response = response.replace(b"<price_Measure_Unit.name>MWH</price_Measure_Unit.name>", b"")

        summary = probe.parse_response(response)

        self.assertIsNone(summary.rows[0].currency)
        self.assertIsNone(summary.rows[0].unit)

    def test_dotenv_token_read_without_echoing(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text("ENTSOE_API_TOKEN='test-token-value'\n", encoding="utf-8")
            self.assertEqual(probe._read_dotenv_token(dotenv), "test-token-value")

    def test_authentication_error_does_not_echo_token(self):
        token = "sensitive-test-token"
        error = urllib.error.HTTPError(
            f"{probe.API_URL}?securityToken={token}", 401, "Unauthorized", {}, None
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
            status, payload = probe.request_prices(token)

        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.assertEqual(query["documentType"], ["A44"])
        self.assertEqual(query["in_Domain"], [probe.NO1_EIC])
        self.assertEqual(query["out_Domain"], [probe.NO1_EIC])
        self.assertEqual(query["periodStart"], ["202401010000"])
        self.assertEqual(query["periodEnd"], ["202401020000"])
        self.assertEqual(query["securityToken"], [token])
        self.assertEqual(status, 200)
        self.assertEqual(len(probe.parse_response(payload).rows), 2)

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
