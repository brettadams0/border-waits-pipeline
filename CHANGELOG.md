# Changelog

Notable changes to `border-waits-pipeline`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Nothing has been tagged yet; the
pipeline deploys from `main`, so everything below is live.

## [Unreleased]

### Added

- Hourly ingest of the CBSA and CBP wait feeds into time-keyed Parquet snapshots on an orphan
  `data` branch, with per-run checks in `ingest/checks.py` that write nothing when they fail.
- The daily CBSA monthly-history update from open.canada.ca (`ingest/history.py`).
- A dbt project on DuckDB: staging with time-zone resolution per side of each crossing, marts,
  dbt unit tests, error tests scoped to the current run, and a history-wide warning copy of each.
- `export`: content-hashed Parquet, a summary, the compiled SQL, `manifest.json` and
  `status.json`, deployed to Pages with the dbt docs.
- A failure path: a failed run redeploys the last good export with a `status.json` naming the
  failed step, and opens or comments on one `pipeline-failing` issue, which the next good run
  closes.
- `web/`: the page served at `/border-waits/`, with a SQL console that queries the Parquet in the
  browser, a fallback snapshot for when the export cannot be fetched, and a Chromium test in CI.
- A second schedule line at :47, because GitHub drops many scheduled runs.

### Fixed

- **CBP's coming-hour stamps failed the run.** CBP stamps an update with the hour about to start,
  so a fetch at 15:53 EDT reads `At 4:00 pm EDT`. The rollover in `stg_readings` treated any CBP
  time more than 15 minutes after the fetch as yesterday's, and `source_updated_not_in_future`
  failed the build on what was left. Rollover now applies only to a late-evening time (20:00 or
  later) fetched in the early morning (before 04:00 local); other times keep their published
  value, the error test fires only at 24 hours ahead, and `warn_source_updated_ahead` reports
  anything past 15 minutes. Pinned by unit cases r7–r9, taken from the failing run's artifact.
  <!-- FACT needed (W1): readings affected before the fix — failed runs and/or rows misdated by a day. -->
- **Quarantined snapshots were never excluded.** `stg_readings` compared
  `excluded_snapshots.path`, a path on the `data` branch, with `filename`, which carries the
  local datastore prefix, so no entry could ever match. It now matches on the path suffix. The
  first entries are the two snapshots written by a fixtures test dispatch, whose `fetched_at` was
  the run time rather than a real fetch.
  <!-- FACT needed (W1): rows from the fixtures dispatch that reached the marts before the fix. -->
- **The page shifted as data arrived.** `web/index.html` rendered the featured-crossings table
  empty and the live badge and notes hidden, then filled them in once the export loaded, pushing
  everything below down. The table now ships with placeholder rows for the three Windsor–Detroit
  crossings, and `web/styles.css` reserves height for the badge, notes, chart and pipeline panel.
  Desktop CLS fell from 0.41 to 0.013 — lab measurement, headless Chrome 156 at 1280×800, 10 runs
  per state, unthrottled. Mobile (390×844) measured 0.000 before and after, which says nothing
  about slow connections, since those weren't tested.
