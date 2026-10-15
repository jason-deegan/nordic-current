# Nordic Current

I built Nordic Current as a personal demonstration project to develop and show
my practical skills in Python, data engineering, and applied analysis. I use
real Norwegian energy data to explore how hydropower reservoir levels vary
across electricity areas and how they might eventually be considered alongside
market prices.

I want to show how I approach practical analytical problems: finding useful
data sources, building reliable workflows, and turning raw data into
something that can support further analysis.

## What it does today

The working NVE pipeline retrieves weekly reservoir statistics from the
[Magasinstatistikk API](https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData)
for Norway's five electricity areas. It validates the response fields, dates,
types, area coverage, and duplicate area/date records; stores the raw response
with retrieval metadata and a checksum; and writes a normalized CSV and
inspection report. A checksum-verified local cache avoids another request for
24 hours unless `--force` is used.

The normalized `filling_fraction` is a ratio (`0.75` means 75%), not a
percentage. The pipeline retains slightly-over-full readings rather than
clamping them.

## Local visualization

A self-contained HTML report plots the NVE weekly filling history for NO1–NO5
and, separately, the locally validated NO1 hourly prices for 1 January 2024.
Explore the reservoir chart with 5-year, 10-year, and full-history views;
toggle areas independently and hover or focus either chart for values. The
time ranges are different, so the charts are not joined and should not be read
as evidence of a relationship.

Refresh both source datasets first, then generate the report:

```text
python scripts/refresh_nve_reservoirs.py
python scripts/refresh_entsoe_prices.py --zone NO1 --start 2024-01-01 --end 2024-01-01
python scripts/build_visualization.py
```

Open `data/processed/nordic_current_report.html` in a browser (in Windows
PowerShell, run `Start-Process .\data\processed\nordic_current_report.html`).
The report is built from local CSV files using only the Python standard
library; it does not need a live connection or token to open. If either CSV is
missing, the generator names the missing file and points to the refresh step.

The generated report and its price chart remain local and are excluded from
Git. ENTSO-E's applicable reuse terms have not yet been confirmed, so do not
publish or redistribute price observations or the report until those terms
have been checked. The generator code and tests may be published; any public
demo artifact should use only data whose publication terms have been confirmed.

## ENTSO-E price data

An authenticated ENTSO-E request and normalized data path are now implemented
for NO1. The request validates the returned bidding-zone identifier, UTC
period, hourly observation continuity, and EUR/MWh units. It can save the raw
XML with token-free retrieval metadata and a normalized CSV. Requests accept
inclusive Norwegian market dates and are limited to 31 calendar dates.

The live one-day check for 1 January 2024 returned 24 hourly observations in
EUR/MWh, with no duplicate timestamps or gaps. Its period was
`2023-12-31T23:00:00Z` to `2024-01-01T23:00:00Z`: the ENTSO-E request dates
refer to Norwegian market days, while the data layer stores timestamps in UTC.
Only this NO1 sample has been checked live. Longer windows, broad historical
coverage, and NO2–NO5 have not been validated.

## Tools and approach

The data pipeline and tests use Python's standard library, so there are no
third-party packages to install. Automated offline tests use synthetic fixtures
and mocked network requests; they check validation, normalization, caching,
and report generation without depending on a live API or token. Keeping
retrieval, validation, and output generation in reusable Python modules makes
the workflows easier to test, maintain, and rerun. Retrieval metadata and
explicit checks make the data provenance and assumptions easier to inspect.

## What this demonstrates

The current code demonstrates working with a public external API, converting
raw responses into structured data, validating real-world records, and
building a reusable, tested workflow. It also documents source provenance and
data limitations. This is a concrete example of applying technical tools to
an energy-market question; it does not yet establish analytical findings or
business impact.

## Current status and next steps

NVE reservoir ingestion and a bounded, live-checked NO1 ENTSO-E price workflow
are implemented and tested. The ENTSO-E connection requires an approved
account and a local token. Synthetic test responses are not market
observations. The local HTML report presents separate interactive source
charts; combined analysis is a possible future stage.

## Getting started

Python **3.10 or newer** is required. Run these commands from the project
directory; no package installation is needed:

```text
python --version
python scripts/refresh_nve_reservoirs.py
```

For ENTSO-E, set `ENTSOE_API_TOKEN` in your environment or copy
`.env.example` to the ignored local `.env` file and add the token there. Never
put a real token in `.env.example` or commit `.env`. Run the small read-only
NO1 check with:

```text
python scripts/test_entsoe_prices.py
```

To retrieve and save an inclusive NO1 market-date window (maximum 31 dates):

```text
python scripts/refresh_entsoe_prices.py --zone NO1 --start 2024-01-01 --end 2024-01-01
```

Raw ENTSO-E XML and token-free retrieval metadata are written to `data/raw/`;
the normalized price table is written to `data/processed/`. Generated data are
excluded from Git by default.

To request fresh data even if the cache is under 24 hours old:

```text
python scripts/refresh_nve_reservoirs.py --force
```

The refresh generates raw data and retrieval metadata under `data/raw/`, a
normalized CSV under `data/processed/`, and a dated inspection snapshot under
`reports/`. The datasets are excluded from Git by default and can be
regenerated with the refresh command.

Run the offline test suite with:

```text
python -B -m unittest discover -s tests -v
```

## Data sources and limitations

NVE's API documentation identifies the reservoir data as licensed under the
Norwegian Licence for Open Government Data (NLOD), compatible with CC BY 3.0
Norway. Attribute NVE when reusing the data; see the
[NLOD terms](https://data.norge.no/nlod/en) and
[NVE source documentation](https://api.nve.no/doc/magasinstatistikk/).
These third-party data terms are separate from the MIT licence for this
project's original code; the code licence does not relicense NVE data.

The weekly series aggregates monitored reservoir statistics by electricity
area; it is not a record of every individual reservoir. The data are
descriptive and do not establish causal relationships. The ENTSO-E check
validates one NO1 day only. It does not establish broad historical coverage or
comparability across all Norwegian zones. Any future combined analysis should
first establish an appropriate common date range and time aggregation, and
should describe associations rather than causal effects. Review ENTSO-E's
applicable data terms before redistributing price observations.

See [DATA_FEASIBILITY.md](DATA_FEASIBILITY.md) for the source investigation,
coverage checks, alignment caveats, and ENTSO-E access requirements.
