import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from nordic_current import reservoirs, visualization


def write_reservoir_csv(path: Path, dates: tuple[date, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=reservoirs.CSV_COLUMNS)
        writer.writeheader()
        for week_index, observed_date in enumerate(dates):
            iso = observed_date.isocalendar()
            for area_index, area in enumerate(reservoirs.AREAS):
                writer.writerow(
                    {
                        "date": observed_date.isoformat(),
                        "area": area,
                        "iso_year": iso.year,
                        "iso_week": iso.week,
                        "filling_fraction": 0.5 + area_index * 0.05 + week_index * 0.01,
                        "capacity_twh": 10,
                        "stored_twh": 5,
                        "previous_filling_fraction": 0.49,
                        "change_fraction": 0.01,
                    }
                )


def write_price_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=visualization.PRICE_COLUMNS)
        writer.writeheader()
        start = datetime(2023, 12, 31, 23, tzinfo=timezone.utc)
        for hour in range(24):
            writer.writerow(
                {
                    "area": "NO1",
                    "timestamp_utc": (start + timedelta(hours=hour))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "price": f"{40 + hour / 2:.2f}",
                    "currency": "EUR",
                    "unit": "MWH",
                    "resolution": "PT60M",
                }
            )


class VisualizationTests(unittest.TestCase):
    def test_render_html_includes_both_accessible_charts_and_limitations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservoir_path = root / "reservoirs.csv"
            price_path = root / "prices.csv"
            output_path = root / "report.html"
            write_reservoir_csv(
                reservoir_path,
                (date(2024, 1, 7), date(2024, 1, 14)),
            )
            write_price_csv(price_path)

            report_path = visualization.build_report(
                root,
                reservoir_csv=reservoir_path,
                price_csv=price_path,
                output_path=output_path,
            )

            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Weekly reservoir filling by electricity area", report)
            self.assertIn("NO1", report)
            self.assertIn("NO5", report)
            self.assertIn("Reservoir filling (%)", report)
            self.assertIn("2024-01-07", report)
            self.assertIn("NO1 hourly day-ahead electricity prices", report)
            self.assertIn("EUR/MWh", report)
            self.assertIn("ENTSO-E Transparency Platform", report)
            self.assertIn(
                "https://biapi.nve.no/magasinstatistikk/api/"
                "Magasinstatistikk/HentOffentligData",
                report,
            )
            self.assertIn("do not publish or redistribute", report)
            self.assertIn('data-range="5y"', report)
            self.assertIn('data-range="10y"', report)
            self.assertIn('data-range="all"', report)
            self.assertIn('data-area-toggle value="NO1" checked', report)
            self.assertIn('data-area-toggle value="NO5" checked', report)
            self.assertIn('id="chart-data" type="application/json"', report)
            self.assertIn('addEventListener("pointermove"', report)
            self.assertIn('addEventListener("keydown"', report)
            self.assertIn(
                "Applicable ENTSO-E reuse terms have not been confirmed.",
                report,
            )
            self.assertNotIn("https://cdn.", report)
            self.assertIn('aria-labelledby="reservoir-chart-title reservoir-chart-desc"', report)
            self.assertIn('aria-labelledby="price-chart-title price-chart-desc"', report)
            self.assertEqual(report.count("<svg "), 2)

    def test_missing_input_has_refresh_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                visualization.VisualizationDataError,
                "Refresh the source data",
            ):
                visualization.build_report(root)

    def test_reject_reservoir_duplicate_and_irregular_week(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "reservoirs.csv"
            write_reservoir_csv(
                path,
                (date(2024, 1, 7), date(2024, 1, 14)),
            )
            contents = path.read_text(encoding="utf-8")
            path.write_text(contents + contents.splitlines()[1] + "\n", encoding="utf-8")
            with self.assertRaisesRegex(visualization.VisualizationDataError, "duplicate"):
                visualization.load_reservoir_series(path)

            write_reservoir_csv(
                path,
                (date(2024, 1, 7), date(2024, 1, 21)),
            )
            with self.assertRaisesRegex(visualization.VisualizationDataError, "irregular weekly"):
                visualization.load_reservoir_series(path)

    def test_reject_reservoir_areas_with_different_date_grids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reservoirs.csv"
            dates = (date(2024, 1, 7), date(2024, 1, 14), date(2024, 1, 21))
            write_reservoir_csv(path, dates)
            with path.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
            rows = [
                row for row in rows
                if not (row["area"] == "NO5" and row["date"] == dates[0].isoformat())
            ]
            with path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=reservoirs.CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaisesRegex(
                visualization.VisualizationDataError,
                "do not share the same weekly dates",
            ):
                visualization.load_reservoir_series(path)

    def test_reject_incomplete_price_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv"
            write_price_csv(path)
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(visualization.VisualizationDataError, "all 24"):
                visualization.load_price_series(path)

    def test_reject_duplicate_price_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv"
            write_price_csv(path)
            with path.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
            rows[1]["timestamp_utc"] = rows[0]["timestamp_utc"]
            with path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=visualization.PRICE_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaisesRegex(visualization.VisualizationDataError, "duplicate"):
                visualization.load_price_series(path)


if __name__ == "__main__":
    unittest.main()
