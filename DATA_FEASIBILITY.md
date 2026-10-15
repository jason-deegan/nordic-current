# Nordic Current: data-feasibility findings

**Investigation date:** 14 October 2026
**Scope:** Official source investigation, live public-data retrieval, and small reproducible data tools. No dashboard was created; credential values are not included in this report.

## Recommendation

**Proceed with staged integration:** NVE's public weekly reservoir-filling API is directly accessible and has a long history. ENTSO-E API access is now authenticated locally; a bounded NO1 day-ahead request has been validated live and a reusable, size-limited data module is implemented. Continue treating price coverage and comparisons outside the verified sample as unconfirmed.

Start comparisons from the first date for which the chosen price-zone definitions and both datasets are genuinely comparable. In particular, do not assume all five current bidding zones have equivalent histories. Preserve source timestamps and market resolution, and describe reservoir/price results as associations, not causal effects.

## Sources and access

| Source | Appropriate mechanism | Access and result |
|---|---|---|
| [NVE Magasinstatistikk API documentation](https://api.nve.no/doc/magasinstatistikk/) and [OpenAPI definition](https://biapi.nve.no/magasinstatistikk/swagger/v1/swagger.json) | `GET https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData` for history; `.../HentOffentligDataSisteUke` for the latest publication; `.../HentOmr%C3%A5der` for area metadata. The API also documents a Min/Max/Median endpoint for the last 20 years. | Tested successfully without registration, token, or credentials. Responses are JSON. NVE's API documentation states NLOD (compatible with CC BY 3.0 Norway); attribute NVE and retain source provenance. |
| [NVE HydAPI documentation](https://api.nve.no/doc/hydrologiske-data/) and [HydAPI user documentation](https://hydapi.nve.no/UserDocumentation/) | REST API: for example, `/api/v1/Stations`, `/api/v1/Series`, `/api/v1/Parameters`, and `/api/v1/Observations`. Use series metadata to select a station, parameter, and available resolution before querying observations. | NVE says the observations are open, but every API request requires an `X-API-Key`. The key is generated after user registration at [HydAPI](https://hydapi.nve.no/Users). No key was requested or used, so no hydrological observation request was made. The docs license these data under NLOD / CC BY 3.0 Norway. |
| [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/), [official token instructions](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token), and [official platform overview](https://www.entsoe.eu/data/transparency-platform/) | Web API day-ahead prices use `documentType=A44`, EIC bidding-zone identifiers in `in_Domain` and `out_Domain`, and `periodStart` / `periodEnd`. A tested one-market-date NO1 request uses the same date for both bounds: `periodStart=202401010000&periodEnd=202401010000`. | An initial request without a security token returned **HTTP 401**. Following account registration, verification, emailed API-access request and approval, the user obtained a token independently. An authenticated single-day NO1 request was later tested successfully; details are recorded below. The token is supplied as the `securityToken` query parameter and is not included in project documentation or retrieval metadata. The API guide URL, [Web API Guide](https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html), remained unavailable to the fetcher (HTTP 400); the official support article confirms the access workflow and token parameter. |
| [Nord Pool Power Market Data Services](https://www.nordpoolgroup.com/en/services/power-market-data-services/) | Nord Pool advertises historical power-market data, including day-ahead prices, dating to 1992. | It is the market operator's primary source, but the page describes a market-data service, not a simpler unrestricted historical API or download mechanism. No Nord Pool price data were tested. |
| [Statistics Norway: Electricity prices](https://www.ssb.no/en/energi-og-industri/energi/statistikk/elektrisitetspriser) and [StatBank table 08307](https://www.ssb.no/en/statbank/table/08307/) | Official statistics on electricity prices and customer contracts. | Useful for retail/customer-price context, but not a direct hourly day-ahead series per NO1–NO5; it is not a substitute for the intended zonal wholesale-price comparison. The StatBank page is a client-rendered application, and no StatBank query was made. |

The ENTSO-E platform overview says the platform launched on 5 January 2015 and separately links legacy data from 2011–2014. That is platform-level coverage information, **not** confirmation that every Norwegian zone's day-ahead series is complete from those dates. Confirm price-specific coverage with authenticated requests before selecting the application's common analysis period. The official [EIC approved-code list](https://www.entsoe.eu/data/energy-identification-codes-eic/) identifies these bidding-zone domains:

| Area | ENTSO-E EIC domain |
|---|---|
| NO1 | `10YNO-1--------2` |
| NO2 | `10YNO-2--------T` |
| NO3 | `10YNO-3--------J` |
| NO4 | `10YNO-4--------9` |
| NO5 | `10Y1001A1001A48H` |

Maintain this mapping explicitly rather than inferring EIC codes from area labels.

## Live checks and observations

### NVE reservoir filling

The full history endpoint returned **14,913 rows** on 14 October 2026, covering **1995-01-08 through 2026-10-04**. Its `EL` (elspot) records contained **1,657 distinct weekly dates for each of NO1–NO5**, with no missing weekly dates or duplicate zone/date pairs inside those returned spans. The four inspected fields (`dato_Id`, `fyllingsgrad`, `kapasitet_TWh`, and `fylling_TWh`) had no null values in those elspot rows. These are checks of the returned API snapshot; they do not establish that any underlying measurement is error-free.

The latest-week endpoint returned records dated `2026-10-04`; the sample for NO1 reported `fyllingsgrad: 0.7513783`, `kapasitet_TWh: 6.0032635`, and `fylling_TWh: 4.510722`. `fyllingsgrad` is a fraction (multiply by 100 for percent), not a value already in percent. The returned historical elspot values ranged from about `0.05165` to `1.02007`; do not clamp values above 1. The schema also provides ISO year/week, previous-week filling, and the weekly change.

`dato_Id` is a weekly calendar date (the observed dates in this dataset are Sundays), not an hourly timestamp. `neste_Publiseringsdato` is publication metadata, not the observation time. The API documents zone rows (`omrType: "EL"`, `omrnr: 1..5`) as well as national (`NO`) and hydrological (`VASS`) areas. `HentOmråder` supplies Norwegian area descriptions. Zone-level reservoir statistics are aggregated measures, not individual reservoir measurements or inflow.

NVE's explanatory page says it collects readings from 489 important reservoirs, while the API description refers to 490. This small source-document discrepancy reinforces that the series represents NVE's monitored/selected reservoir portfolio; it should not be described as a census of every Norwegian reservoir.

### Hydrological observations

The HydAPI documentation reports historical observations from approximately 1,800 stations and around 8,500 series, including discharge, water level, snow, groundwater, and temperatures. It documents instantaneous, hourly, and daily resolutions; station and series metadata include available date ranges, which can be incomplete or null. Observation requests are bounded and rate-limited, and the docs advise small, cached requests. Since obtaining data requires registration and a key, only the documentation—not a real hydrological series—was checked. Hydrological series are useful for a later inflow/runoff analysis, but they are not needed for the initial reservoir-filling comparison.

### Day-ahead prices

An unauthenticated ENTSO-E `A44` request returned **HTTP 401** during the initial source investigation. A later authenticated request for NO1 market date 2024-01-01 returned HTTP 200, 24 hourly observations, and EUR/MWh metadata. ENTSO-E returned the interval `2023-12-31T23:00:00Z` to `2024-01-01T23:00:00Z`; the 24 observation timestamps were unique and exactly one hour apart. This verifies only that one date and zone, not broad historical coverage or other areas. Preserve source intervals and validate each response rather than assuming a fixed resolution. Check ENTSO-E's applicable reuse terms before redistributing price data.

The price geography is represented by ENTSO-E EIC domain codes, whereas NVE uses the human-readable elspot area type and number. The source mapping is documented above, but the implemented and live-validated price module currently supports NO1 only. The tested response declared EUR/MWh and PT60M. Price areas can change over time; do not treat every current area's historical price series as if it existed unchanged throughout NVE's full history. Limit comparisons to periods where each area's price definition is valid and available.

## Temporal and geographic alignment

The data can be aligned meaningfully **at weekly, zone level**, subject to the caveats above:

1. The API request bounds are inclusive Norwegian market dates; returned timestamp boundaries are timezone-aware and normalized to UTC by the data module. Do not join a UTC timestamp directly to an NVE date without an explicit rule.
2. Group the prices for each valid zone into a clearly defined week (for example, the ISO week containing the NVE `dato_Id`) and calculate an explicitly named statistic such as mean or median. Keep the number of price observations used and flag incomplete weeks.
3. Join that weekly statistic to NVE's `EL` record using the verified area map and ISO year/week (or the calendar date after confirming its week convention). The NVE observation is a weekly reservoir snapshot; associating it with a same-week or following-week price summary is a descriptive convention, not evidence that the snapshot caused the price.
4. Restrict geography/date coverage to the intersection of valid reservoir and price-area histories. For earlier periods or zone changes, either exclude affected zones/years or label a separately defined historical-area comparison; do not backfill a present-day zone price by assumption.

This supports seasonal and weekly descriptive comparisons, but reservoir filling alone omits many influences on prices, including inflow, demand, weather, fuel costs, interconnector flows, and transmission constraints. Any apparent relationship is observational, not causal.

## Recommended small-project architecture

- Keep the sources separate behind two small ingestion functions: one for NVE weekly JSON, one for ENTSO-E price documents.
- Fetch NVE's small weekly aggregate dataset directly and cache the raw response with its retrieval time. For ENTSO-E, backfill in bounded date windows per zone, then refresh only recent windows; cache raw responses and normalize them locally.
- Use one local SQLite database (or equivalent small local file store) with separate `reservoir_weekly` and `day_ahead_prices` tables plus a source/retrieval record. Preserve source identifiers, raw timestamp, resolution, currency/unit, and missingness flags; derive weekly price summaries rather than discarding interval data.
- Read the ENTSO-E token from an untracked local secret/environment configuration. Never put it in source, report output, URLs stored in logs, or committed files. HydAPI credentials are unnecessary for the reservoir-filling endpoint.
- Before plotting or calculating, validate expected zones, duplicate keys, missing intervals, NVE weekly coverage, units, and valid area-history dates. Cite NVE/ENTSO-E as sources and review the applicable ENTSO-E platform/data conditions before publishing or redistributing data. NVE's NLOD attribution conditions are clearer and were confirmed from its docs; ENTSO-E's current reuse terms could not be independently verified here.

This avoids a database server, large historical download, and unnecessary hydrology dependency while keeping the later application reproducible. Registration, explicit API-access approval, and token generation are the access prerequisites for the intended historical zonal price source.

## Responsible analytical questions

1. How do weekly day-ahead price levels and price spreads between valid Norwegian bidding zones vary by season?
2. Within each zone, how are weekly reservoir filling levels and week-to-week changes associated with same-week or next-week price summaries?
3. Are weeks with unusually low reservoir filling associated with higher prices or wider between-zone price spreads, after stratifying results by season and clearly stating the observed date range?

For all three, report the time window, missingness, sample size, aggregation rule, and price-zone coverage; avoid presenting the patterns as causal effects.

## Reproduction commands

Commands below were run in Windows PowerShell. The reservoir checks request the full aggregate history once; no files were written.

```powershell
# Sample the current week's public reservoir data
Invoke-RestMethod -Uri 'https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligDataSisteUke' -Method Get

# Retrieve and count the full history
$d = Invoke-RestMethod -Uri 'https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData' -Method Get
$d.Count
$d | Group-Object omrType | ForEach-Object { $_.Name + '=' + $_.Count }
$z = $d | Where-Object omrType -eq 'EL'
foreach ($group in ($z | Group-Object omrnr | Sort-Object Name)) {
    $dates = @($group.Group | ForEach-Object { [datetime]$_.dato_Id } | Sort-Object -Unique)
    $start = $dates[0]
    $end = $dates[-1]
    $expectedWeeks = [int](($end - $start).TotalDays / 7) + 1
    'NO{0}: rows={1}; unique_dates={2}; absent_weeks={3}; {4}..{5}' -f `
        $group.Name, $group.Count, $dates.Count, ($expectedWeeks - $dates.Count), `
        $start.ToString('yyyy-MM-dd'), $end.ToString('yyyy-MM-dd')
}
foreach ($field in @('dato_Id', 'fyllingsgrad', 'kapasitet_TWh', 'fylling_TWh')) {
    $nullCount = @($z | Where-Object { $null -eq $_.$field }).Count
    "$field nulls=$nullCount"
}
$duplicateCount = @(
    $z | Group-Object { '{0}|{1}' -f $_.omrnr, $_.dato_Id } |
        Where-Object Count -gt 1
).Count
"duplicate zone/date pairs=$duplicateCount"
$z | Measure-Object fyllingsgrad -Minimum -Maximum

# Check the original ENTSO-E day-ahead request without a token
$u = 'https://web-api.tp.entsoe.eu/api?documentType=A44&in_Domain=10YNO-1--------2&out_Domain=10YNO-1--------2&periodStart=202401010000&periodEnd=202401020000'
Invoke-WebRequest -Uri $u -Method Get
```

Observed results: NVE returned JSON; the full history count was 14,913 (`EL=8285`, `NO=1657`, `VASS=4971`); each `EL` zone had 1,657 weekly rows from 1995-01-08 to 2026-10-04; the original unauthenticated ENTSO-E request returned HTTP 401. The published documentation links above were also fetched, except the ENTSO-E API Guide URL (HTTP 400). A later authenticated price request is documented below.

## ENTSO-E API registration and token steps

The official [Transparency Platform help article on security tokens](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token) gives this sequence:

1. Go to the [production Transparency Platform](https://transparency.entsoe.eu/), select **Sign In**, use its **Register** link, and complete registration.
2. Verify the account using the URL sent to the registered email address.
3. Email `transparency@entsoe.eu` with the exact subject **RESTful API access** and the registered email address in the message body.
4. Wait for ENTSO-E's confirmation. The article says access is granted within three working days and confirmed by email.
5. Sign in, open **My Account**, and generate a new security token. Treat that token as a secret.

The original feasibility investigation did not request account access or generate a token; the user later obtained API access independently. The local project uses production, because ENTSO-E's test environment has less data.

## Small authenticated NO1 probe

The standard-library probe [scripts/test_entsoe_prices.py](./scripts/test_entsoe_prices.py) makes a read-only request for the NO1 market date **2024-01-01** (`A44`, EIC `10YNO-1--------2`). The API treats the supplied date bounds as inclusive market dates, so a one-date request uses the same date for `periodStart` and `periodEnd`. Returned timestamps are parsed as timezone-aware values and normalized to UTC. The probe reports HTTP status, returned interval, count, resolution, currency, and unit, and rejects incomplete or misaligned responses. It never prints the request URL, token, response body, or raw exception text.

Configuration options:

- **Environment variable:** set `ENTSOE_API_TOKEN` in the shell that runs the script.
- **Local file:** copy [.env.example](./.env.example) to `.env` and place the token after `ENTSOE_API_TOKEN=`. `.gitignore` excludes `.env` and `.env.*` while allowing the safe `.env.example`.

With Python 3.10 or newer installed, run these commands from the project directory (the test suite was verified with Python 3.14.3):

```text
python scripts/test_entsoe_prices.py
python -B -m unittest discover -s tests -v
```

Copy `.env.example` to `.env` using your file manager, then edit the local file
without sharing the token.

The authenticated request was tested on 14 October 2026. For market date
2024-01-01 it returned HTTP 200 and 24 hourly observations in EUR/MWh. The
declared interval was `2023-12-31T23:00:00Z` to `2024-01-01T23:00:00Z`;
timestamps were unique and consecutive at one-hour intervals. This verifies a
single NO1 day only, not broad price history, other zones, or cross-dataset
comparability. The access token is held only in the ignored local `.env` or
environment and is not written to response metadata.

The reusable module
[nordic_current/prices.py](./nordic_current/prices.py) supports bounded
inclusive date windows for NO1 (up to 31 dates), verifies the returned EIC,
EUR/MWh units, UTC period bounds, resolution, and observation continuity, and
writes raw XML, token-free retrieval metadata, and a normalized CSV. The
refresh command is:

```text
python scripts/refresh_entsoe_prices.py --zone NO1 --start 2024-01-01 --end 2024-01-01
```

Automated ENTSO-E tests use a synthetic complete-day XML fixture. The fixture
is only for deterministic testing and is not presented as observed market
data. No combined price/reservoir analysis or dashboard is included.

## Implemented NVE data layer and current snapshot

The reusable, Streamlit-independent NVE module is
[nordic_current/reservoirs.py](./nordic_current/reservoirs.py). It validates
the five `EL` areas, required source columns, ISO dates and week identifiers,
numeric fields, duplicate area/date keys, missing values, and the fractional
interpretation of `fyllingsgrad`. Fractions up to 1.1 are accepted so that
slightly-over-full historic observations are retained rather than silently
clamped. A checksum-verified 24-hour cache avoids repeat requests; pass
`--force` to the CLI to refresh it.

Refresh from the project directory with Python 3.10 or newer:

```text
python scripts/refresh_nve_reservoirs.py
```

The raw response is stored at `data/raw/nve_reservoirs.json`, with retrieval
time, source URL, HTTP status, and SHA-256 in
`data/raw/nve_reservoirs.metadata.json`. The validated normalized table is
`data/processed/nve_reservoirs.csv`. Run
`scripts\refresh_nve_reservoirs.py --force` to bypass a fresh cache. The local
inspection report at `reports/nve_reservoir_inspection.md` separates measured
snapshot counts and coverage from contextual claims drawn from NVE source
documentation.

At the live retrieval on 14 October 2026, the API returned 8,285 elspot rows
(1,657 per area), from 1995-01-08 through 2026-10-04. All five area/date spans
had no missing weekly dates; required normalized values passed validation.
These are observations from this saved API response, not a guarantee about
future responses or the quality of underlying measurements.

The authenticated NO1 sample retrieved on 14 October 2026 is saved locally as
raw XML with retrieval metadata and a normalized CSV. The raw and processed
price files are excluded from Git by default. Automated tests use a separate
synthetic XML fixture; those fixture values are not presented as market
observations. No combined price/reservoir analysis or dashboard is included.
