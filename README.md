# Nordic Current

Nordic Current is a personal demonstration project built around a practical
energy-sector data problem: how Norwegian hydropower reservoir levels vary
across electricity areas, and how they might later be explored alongside
market prices. I use it to develop and demonstrate practical skills in Python,
data engineering, and applied analysis using real public data.

The aim is to demonstrate how I approach practical analytical problems:
identifying useful data sources, building reliable workflows, and turning raw
data into something that can support further analysis.

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

## Tools and approach

The data pipeline and tests use Python's standard library, so there are no
third-party packages to install. Automated offline tests use synthetic fixtures
and mocked network requests; they check validation, normalization, caching,
and report generation without depending on a live API. Keeping retrieval,
validation, and output generation in a reusable Python module makes the
workflow easier to test, maintain, and rerun. Retrieval metadata and explicit
checks make the data provenance and assumptions easier to inspect.

## What this demonstrates

The current code demonstrates working with a public external API, converting
raw responses into structured data, validating real-world records, and
building a reusable, tested workflow. It also documents source provenance and
data limitations. This is a concrete example of applying technical tools to
an energy-market question; it does not yet establish analytical findings or
business impact.

## Current status and next steps

NVE reservoir-data ingestion is implemented and tested. An ENTSO-E NO1
day-ahead price probe is prepared, but it has not been validated against live
price data: API access requires registration and ENTSO-E approval. Synthetic
test responses are not market observations. Analysis combining prices and
reservoir levels, and a dashboard, are possible future stages; neither is
currently included.

## Getting started

Python **3.10 or newer** is required. Run these commands from the project
directory; no package installation is needed:

```text
python --version
python scripts/refresh_nve_reservoirs.py
```

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
descriptive and do not establish causal relationships. Price coverage,
resolution, and comparability across zones still need to be verified with
authenticated ENTSO-E data before any combined analysis.

See [DATA_FEASIBILITY.md](DATA_FEASIBILITY.md) for the source investigation,
coverage checks, alignment caveats, and ENTSO-E access requirements.
