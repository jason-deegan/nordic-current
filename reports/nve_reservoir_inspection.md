# NVE reservoir data inspection — snapshot retrieved 2026-10-14

## Live observation snapshot

- Retrieved: `2026-10-14T07:34:57.903873+00:00`
- Source endpoint: [https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData](https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData)
- HTTP status: 200
- SHA-256 of raw response: `468601a74ca8feaf13e21b614a4094f86286d8a230e036edc8eec66f0a04df26`
- Normalized rows: 8285
- Coverage: 1995-01-08 to 2026-10-04
- Normalized fraction fields are ratios (for example, 0.75 means 75%), not percentages.
- Missing values in the normalized required fields: 0 (validation rejects null or non-numeric values).

| Area | Rows | First week | Last week | Missing weekly dates |
|---|---:|---|---|---:|
| NO1 | 1657 | 1995-01-08 | 2026-10-04 | 0 |
| NO2 | 1657 | 1995-01-08 | 2026-10-04 | 0 |
| NO3 | 1657 | 1995-01-08 | 2026-10-04 | 0 |
| NO4 | 1657 | 1995-01-08 | 2026-10-04 | 0 |
| NO5 | 1657 | 1995-01-08 | 2026-10-04 | 0 |

Unique weeks with at least one area record: 1657. Missing weekly area-dates within each area's span: 0.
Weekly-frequency check uses the observed calendar dates; this is not evidence that NVE's underlying measurements are error-free.

## Source-documentation context (not live measurements)

NVE describes the series as weekly filling statistics for its monitored major reservoir portfolio, grouped by electricity area (`EL`), national area (`NO`), and hydrological area (`VASS`). The OpenAPI schema gives filling fraction, capacity in TWh, and stored volume in TWh. NVE documentation identifies the data as NLOD, compatible with CC BY 3.0 Norway; attribution is required. This documentation context is separate from the live row counts above.
