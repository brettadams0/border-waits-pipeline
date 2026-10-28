# border-waits-pipeline

An hourly pipeline for the border wait estimates that CBSA and CBP publish for the Canada–US land
crossings. It stores every run, models the readings with dbt on DuckDB, tests them, and publishes
Parquet files that a browser can query. The three Windsor–Detroit crossings are featured.

The values are wait **estimates published by CBSA and CBP**, not measured crossing times. The
scheduler is GitHub Actions cron.

## Sources

| Source | URL | Licence |
|---|---|---|
| CBSA, Canada-bound | `https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv` | Open Government Licence – Canada |
| CBP, US-bound | `https://bwt.cbp.gov/xml/bwt.xml` | public domain; cite CBP |
| CBSA monthly history | open.canada.ca dataset `000fe5aa-1d77-42d1-bfe7-458c51dacfef`, checked daily | Open Government Licence – Canada |

Attribution: "Contains information licensed under the Open Government Licence – Canada." and "Source:
U.S. Customs and Border Protection". See `LICENSE-DATA.md`.

## How it runs

`pipeline.yml` is scheduled at :17 and :47 every hour. GitHub drops many scheduled runs (on 2026-10-28 only 3
of ~14 hourly runs fired), so the second line is there to get closer to one reading per hour. Runs are
serialized (`concurrency: pipeline`), and snapshots are keyed by time, so two readings in an hour are fine.
Each run:
1. fetches both feeds, parses them into one normalized row per crossing × direction × lane group, and
   runs the per-run checks (`ingest/checks.py`). A failure writes nothing.
2. writes `snapshots/source=<cbsa|cbp>/date=YYYY-MM-DD/<HHMMSS>.parquet` and the gzipped raw CBSA CSV to
   the orphan `data` branch. The raw CBP XML is kept as a 14-day workflow artifact.
3. runs `dbt build`. Error-severity tests check this run only; each has a warning copy over all of
   history, so one bad old snapshot doesn't block later runs. Freshness is tested separately and
   never blocks.
4. exports `public/data/v1/` (content-hashed Parquet, a summary, compiled SQL, `manifest.json`,
   `status.json`) and the dbt docs, commits the run to `data`, and deploys to this repo's Pages.

On a failure it redeploys the last good export with a `status.json` naming the failing step, and opens
(or comments on) one "pipeline failing" issue. The next good run closes it.

## Schema

One row per crossing × direction × lane group per run: `run_id`, `schema_version`, `fetched_at`,
`source`, `source_crossing_name`, `source_location`, `cbp_port_number`, `port_status`, `direction`
(`to_canada`, `to_us`), `lane` (`travellers`, `commercial`), `lane_type` (`standard`, `nexus_sentri`,
`fast`, `ready`), `status_raw`, `delay_min`, `is_open`, `lanes_open`, `source_updated_raw`,
`source_tz_abbrev`. Raise `schema_version` when a column is added.

`dbt/seeds/dim_crossing.csv` maps the names in each feed to one `crossing_id`, with a time zone for
each side (`cbsa_iana_zone`, `cbp_iana_zone`). Crossings whose pairing isn't stated in the feeds stay
one-sided.

## Running it locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                       # parsers, checks, dbt on fixtures, export
.venv/bin/python -m ingest --run-id local-1 --fixtures
cd dbt && ../.venv/bin/dbt build --profiles-dir . --vars "{run_id: local-1}"
```

## Operations

- **Quarantine a bad snapshot:** add its path on the `data` branch (`snapshots/...`) and a reason to
  `dbt/seeds/excluded_snapshots.csv`. Staging skips it; the `data` branch isn't rewritten.
- **New crossing name:** `unmatched_crossings` warns with the name; add a `dim_crossing` row.
- **Schedule auto-disable:** GitHub disables scheduled workflows in a public repo after 60 days with no
  repository activity. Re-enable it under Actions → pipeline → Enable workflow. Day-61 result:
  not checked yet.
- **First run:** the `data` branch must exist (an orphan branch with an empty commit) before the
  first scheduled run.

## What the feeds actually do

Seen in the live feeds and handled in the code (each has a test):
- CBSA listed 30 crossings on 2026-10-27 (Gordie Howe included).
- CBP writes noon as `At Noon EDT`.
- CBP stamps an update with the coming hour: fetched at 15:53 EDT, several ports said `At 4:00 pm EDT`.
  Some ports run further ahead (International Falls `At 4:00 pm CDT`, 67 min after the fetch; Norton
  `At 8:00 pm EDT`, 4 h after). These keep their published time and show as the
  `warn_source_updated_ahead` warning; only a time a day or more ahead fails the build.
- A late-evening CBP time fetched after local midnight belongs to the day before (published ≥ 20:00,
  fetch < 04:00 local).
- Port Huron's abbreviation can disagree with its zone (`EST` in October); the zone decides.
- The two sides of a crossing can be in different zones (New Brunswick on Atlantic time, Maine on
  Eastern), so `dim_crossing` has a zone per side.

## The page

`web/` holds the page that brettadams0.github.io serves at `/border-waits/`; the site copies it from
here.

## License

Code: MIT. Data: see `LICENSE-DATA.md`.
