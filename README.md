# border-waits-pipeline

[![CI](https://github.com/brettadams0/border-waits-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/brettadams0/border-waits-pipeline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Canada and the US each publish a wait estimate for the same land crossings, and their timestamps
disagree about what hour they mean. CBP stamps a reading with the hour about to start — fetched at
15:53 EDT, it says `At 4:00 pm EDT`. Port Huron reports `EST` in October. The two sides of one
crossing can sit in different time zones. This pipeline fetches both feeds on a schedule, keeps
every run, resolves each timestamp to an instant, models and tests the readings with dbt on DuckDB,
and publishes Parquet that a browser can query. It has no server: GitHub Actions runs it, an orphan
git branch stores it, and GitHub Pages serves it. That choice has a cost, measured below: GitHub's
scheduler fired 16 of the 93 scheduled slots it was given.

**[Live dashboard](https://brettadams0.github.io/border-waits/)** — current waits at the three
Windsor–Detroit crossings, the last run's status, and a SQL console that re-runs one of the
pipeline's own models in your browser and checks the answer against the build.

<!-- HERO (W3): dashboard screenshot — dimensions, weight and alt text to come from W3. -->

## Does it stay correct when the schedule doesn't?

The workflow asks to run at :17 and :47 past every hour. That is an intent, not a rate. Between
2026-10-27 17:47 UTC and 2026-10-30 05:46 UTC, counting every slot the cron lines asked for:

| GitHub's scheduler | |
|---|---:|
| Scheduled slots that fired | **16 of 93 (17%)** |
| Clock hours with a scheduled reading | 13 of 52 |
| Gap between scheduled readings, median | **3.4 h** |
| &nbsp;&nbsp;range | 0.4 – 7.4 h |

That measures GitHub's scheduler, not this pipeline and not the agencies: every run that started
ran ingest, and the gaps are runs GitHub never started. So in practice this is a reading every few hours, not every hour, and anyone
can check that in the Actions tab. The second cron line, at :47, was added to raise the odds of a
run in any given hour; at this rate it doesn't make the schedule hourly.

<!-- PENDING W1: the uptime FACT — data since / successful readings over the window. -->

| Runs, same window | |
|---|---:|
| Scheduled | 16 |
| Started by hand (`workflow_dispatch`) | 7 |
| Succeeded | **19** |
| Failed | 3 |
| In progress when counted | 1 |

What matters more than how often it runs is what a reader sees when a run goes wrong. A failed run
never publishes partial data. It redeploys the last good export with a `status.json` that names the
step that broke, and opens a `pipeline-failing` issue — or comments on the open one — which the next
good run closes. The dashboard goes **stale rather than wrong**, and says which. That path has fired
for real:

- [#1](https://github.com/brettadams0/border-waits-pipeline/issues/1): opened by a deliberate test of
  the path (`fail_ingest`); a real failure then joined it as a comment — `dbt build` refused CBP's
  coming-hour stamps, before that rule existed. Closed by the next good run.
- [#3](https://github.com/brettadams0/border-waits-pipeline/issues/3): a scheduled run's ingest
  refused `10/29/2026 At Midnight MDT`, a form the per-run check doesn't accept yet, so nothing was
  written. Closed by the next good run, once the feed had moved past midnight. CBP writes noon as
  `At Noon`, which is handled; midnight is not, so this can recur.

Old data can't block new data either. Error-severity dbt tests check the current run only, and each
has a warning copy over all of history, so one bad snapshot from last week warns forever but never
stops today's deploy. Two tests build exactly that case from fixtures:
`test_bad_old_snapshot_still_builds` and `test_bad_current_run_fails`.
([`pipeline.yml`](.github/workflows/pipeline.yml), [`run_filter.sql`](dbt/macros/run_filter.sql),
[`test_dbt.py`](tests/test_dbt.py))

## How it works

### Fetch and check

Each run downloads CBSA's CSV (Canada-bound) and CBP's XML (US-bound) and parses them into one row
per crossing × direction × lane group. Before anything is written, the run is checked: each source
must list at least 25 crossings, every delay must be between 0 and 720 minutes, and every timestamp
must match the format the parser was written for. One failure and the run writes nothing.
([`checks.py`](ingest/checks.py), [`cbsa.py`](ingest/cbsa.py), [`cbp.py`](ingest/cbp.py))

### Storage

A run writes `snapshots/source=<cbsa|cbp>/date=YYYY-MM-DD/<HHMMSS>.parquet` and the gzipped raw
CBSA CSV to the orphan `data` branch, which is never rewritten. The raw CBP XML is kept as a
workflow artifact for 14 days. Snapshots are keyed by time, so two readings in an hour are fine.
CBSA's monthly service-standard history is fetched from open.canada.ca once a day.
([`write.py`](ingest/write.py), [`history.py`](ingest/history.py))

### Crosswalk

The two feeds name crossings differently — CBSA by name, CBP by port number.
[`dim_crossing.csv`](dbt/seeds/dim_crossing.csv) maps both to one `crossing_id` and gives each side
its own IANA zone (`cbsa_iana_zone`, `cbp_iana_zone`). Crossings whose pairing isn't stated in the
feeds stay one-sided rather than guessed. A name that appears in a feed with no row here shows up in
`unmatched_crossings` as a warning.

### Models and tests

`stg_readings` resolves timestamps (below). `fct_wait_readings` keeps one row per crossing ×
direction × lane × source update, taking the earliest fetch of each update, because a crossing
updates on its own clock and the same update can be fetched more than once. `agg_wait_by_hour` is the
chart's grain; `agg_wait_by_weekday_hour` exists only for the SQL console, since weekday medians
can't be combined into an all-days median. Freshness is tested separately and never blocks a run.
([`dbt/models/`](dbt/models))

### Export and page

`export` writes content-hashed Parquet (the first 8 hex characters of each file's sha256 in its
name), a summary, the compiled SQL, `manifest.json` and `status.json`, and deploys them with the dbt
docs. The previous run's data files are kept, so a SQL session that started before a deploy can
finish. The page reads only the published export, with no build step, and falls back to a committed
snapshot if the export can't be fetched. Its SQL console is DuckDB-WASM reading the Parquet
directly. ([`export/__main__.py`](export/__main__.py), [`web/`](web))

## Two agencies, one hour

Every reading carries a local wall-clock time and a zone abbreviation, and neither can be trusted
alone. `stg_readings` turns each one into an instant using the IANA zone of the side that
published it, not the abbreviation:

- **The zone decides.** It finds the zone's offset 12 hours either side of the local time and tries
  both. If exactly one gives a valid instant, that is the answer — so Port Huron's `EST` in October
  doesn't move anything.
- **The fall-back hour exists twice.** 01:30 on 2026-11-01 is two instants. There, and only
  there, the abbreviation picks between them, provided the instant it names is not after the fetch.
- **The spring-forward hour doesn't exist.** 02:30 on 2027-03-14 resolves to the valid candidate
  closest to, and not after, the fetch.
- **CBP is ahead on purpose.** A CBP time more than 15 minutes after the fetch is kept as published
  and reported by `warn_source_updated_ahead`; only a time 24 hours ahead fails the build. The one
  exception is a real midnight rollover: a time of 20:00 or later, fetched before 04:00 local,
  belongs to the day before.

Each row records which rule resolved it in `tz_resolved_by` (`zone`, `abbrev` or `rule`) and
whether the abbreviation agreed with the zone, so a reader can audit every timestamp. The
coming-hour rule came from a failed run: CBP said `At 4:00 pm EDT` at 15:53 EDT, the original
not-in-the-future test refused it, and the dbt unit cases now include that run's rows — a +7-minute
stamp, a Central port at +67 minutes, and one at +4 hours, all kept as published.
([`stg_readings.sql`](dbt/models/staging/stg_readings.sql),
[`local_to_instant.sql`](dbt/macros/local_to_instant.sql),
[`unit_tests.yml`](dbt/models/unit_tests.yml))

<!-- FACT needed (W1): counts of tz_resolved_by (zone / abbrev / rule), rows where the abbreviation
disagreed with the zone, and warn_source_updated_ahead rows, over all of history — the measurement
this section needs. -->

The same care applies to the page. The export runs `agg_wait_by_hour`'s compiled SQL over the
published 14-day file and records the row count, a sum and an md5 of the result in the manifest.
The SQL console's rebuild check runs the same SQL over the same file with DuckDB-WASM and compares
all three, so what the browser computes is checked against what CI computed, on screen.
<!-- FACT needed (W3): the rebuild check's result on the live page, and the DuckDB versions on
each side. -->
([`export/__main__.py`](export/__main__.py), [`sql-console.js`](web/sql-console.js))

## Running it

Python 3.13, which CI and the scheduled pipeline use. The tests need no network; they run on the
files in `fixtures/`.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                             # parsers, checks, dbt on fixtures, export
.venv/bin/python -m ingest --run-id local-1 --fixtures    # one run from fixtures/
cd dbt && ../.venv/bin/dbt build --profiles-dir . --vars "{run_id: local-1}"
cd .. && .venv/bin/python -m export --run-id local-1      # writes public/data/v1/
```

`python -m ingest`:

| Flag | Default | |
|---|---|---|
| `--run-id` | required | the id every row from this run carries |
| `--fixtures` | off | read `fixtures/` instead of the network |
| `--datastore` | `datastore` | where snapshots are written (the `data` branch checkout) |
| `--raw-dir` | `raw-artifact` | where raw responses and headers go |
| `--fetched-at` | now | override the run time (tests) |

`python -m export` takes `--run-id` (required), `--db` (`dbt/target/bwt.duckdb`), `--out`
(`public/data/v1`), `--previous` (`datastore/published/data/v1`), `--datastore` (`datastore`),
`--snapshot` (also write the page's `fallback/`), and run metadata that the workflow fills in:
`--run-url`, `--git-sha`, `--data-sha`, `--run-seconds`, `--snapshot-bytes`.

The `pipeline` workflow can be started by hand with two inputs: `fixtures` (use the fixtures
instead of the network) and `fail_ingest` (force a failure, to exercise the failure path). Both
default to off.

## Development

```sh
pip install -r requirements.txt
python -m pytest -q

mkdir -p datastore/history/cbsa_land
cp fixtures/cbsa-history.csv "datastore/history/cbsa_land/2025-12-18T22:31:02.377918.csv"
python -m ingest --run-id ci-1 --fixtures
(cd dbt && dbt build --profiles-dir . --vars "{run_id: ci-1, datastore: ../datastore}" --exclude tag:freshness)
python -m export --run-id ci-1

npm install -g playwright@1.56.1 && playwright install --with-deps chromium
NODE_PATH="$(npm root -g)" node web/test/page.mjs public/data/v1   # the page, in Chromium
```

When a feed does something new, take the raw response from the failing run's `raw-<run id>`
artifact, cut it down to the rows that matter, and add it as a fixture or a dbt unit case in the
same commit as the rule that handles it. A new error-severity test needs its history-wide warning
copy. A new column raises `schema_version`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Operations

- **Quarantine a bad snapshot:** add its path on the `data` branch (`snapshots/...`) and a reason
  to [`excluded_snapshots.csv`](dbt/seeds/excluded_snapshots.csv). Staging skips it; the `data`
  branch isn't rewritten.
- **New crossing name:** `unmatched_crossings` warns with the name; add a `dim_crossing` row.
- **Schedule auto-disable:** GitHub disables scheduled workflows in a public repo after 60 days
  with no repository activity. Re-enable it under Actions → pipeline → Enable workflow. What
  happens on day 61 has not been observed yet.
- **First run:** the `data` branch must exist, as an orphan branch with an empty commit, before
  the first scheduled run.

## Layout

| | |
|---|---|
| [`ingest/`](ingest) | fetch, parse, per-run checks, Parquet writer; no modelling, nothing written if a check fails |
| [`dbt/seeds/`](dbt/seeds) | the crossing crosswalk and the quarantine list; the only hand-edited data |
| [`dbt/models/`](dbt/models) | staging (zones), marts, unit cases; error tests scoped to the current run |
| [`dbt/tests/`](dbt/tests) | singular and generic tests, each error test with a warning copy |
| [`export/`](export) | reads the built database and writes the published files; never touches the feeds |
| [`web/`](web) | the dashboard; no build step, reads only the published export |
| [`fixtures/`](fixtures) | real feed responses with their headers, for tests that need no network |
| [`tests/`](tests) | pytest: parsers, checks, crosswalk, history, dbt on fixtures, the CLI |
| [`.github/workflows/`](.github/workflows) | `ci.yml` on pushes to `main` and pull requests; `pipeline.yml` on the schedule, with the failure path |

The page at `/border-waits/` on brettadams0.github.io is copied from `web/` here; edit it here.

## Sources

| Source | URL | Licence |
|---|---|---|
| CBSA, Canada-bound | `https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv` | Open Government Licence – Canada |
| CBP, US-bound | `https://bwt.cbp.gov/xml/bwt.xml` | public domain; cite CBP |
| CBSA monthly history | open.canada.ca dataset `000fe5aa-1d77-42d1-bfe7-458c51dacfef` | Open Government Licence – Canada |

The values are wait **estimates published by CBSA and CBP**, not measured crossing times.
Attribution: "Contains information licensed under the Open Government Licence – Canada." and
"Source: U.S. Customs and Border Protection". See [LICENSE-DATA.md](LICENSE-DATA.md).

## License

Code: MIT — see [LICENSE](LICENSE). Data: see [LICENSE-DATA.md](LICENSE-DATA.md).
