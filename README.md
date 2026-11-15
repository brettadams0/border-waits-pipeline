# border-waits-pipeline

A scheduled pipeline for the border wait estimates that CBSA and CBP publish for the Canada–US land
crossings. It stores every run, models the readings with dbt on DuckDB, tests them, and publishes
Parquet files that a browser can query. The three Windsor–Detroit crossings are featured.

The values are wait **estimates published by CBSA and CBP**, not measured crossing times. The
scheduler is GitHub Actions cron, which is best-effort: the schedule asks for two runs an hour and the
median gap between runs in the first weeks was about three hours. The manifest's `cadence` block and
the page's run strip report what was actually achieved.

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
of ~14 hourly runs fired), so the second line raises the odds of a reading in a given hour; it guarantees
nothing. Runs are serialized (`concurrency: pipeline`), and snapshots are keyed by time, so two readings in
an hour are fine. Each run:
1. fetches both feeds (up to 3 attempts on a timeout, 429 or 5xx; `ingest/fetch.py`), parses them into
   one normalized row per crossing × direction × lane group, and runs the per-run checks
   (`ingest/checks.py`): the row contract, real dates, 25 crossings per source. A failure writes nothing.
2. writes `snapshots/source=<cbsa|cbp>/date=YYYY-MM-DD/<HHMMSS>.parquet` and the gzipped raw CBSA CSV and
   **commits them to the orphan `data` branch straight away** (`scripts/commit-data.sh ingest`), before
   anything downstream can fail. The raw CBP XML is kept as a 14-day workflow artifact.
3. runs `dbt build`. Error-severity tests check this run only; each has a warning copy over all of
   history, so one bad old snapshot doesn't block later runs. Freshness is tested separately and
   never blocks.
4. exports `public/data/v1/` (content-hashed Parquet, a summary, compiled SQL, `manifest.json`,
   `status.json`) and the dbt docs, commits the export to `data` as a second commit
   (`commit-data.sh publish`), and deploys to this repo's Pages from a separate job.

When dbt or the export fails, the run's snapshots are already stored and `published/` on the data branch
still holds the last good export. The failure job (`python -m export.recover`) redeploys that export
together with the dbt docs that are live, under a `status.json` naming the failing step and whether the
readings were collected, and opens (or comments on) one "pipeline failing" issue. The next good run
closes it. If no run has ever succeeded, the site holds only that `status.json` and the page shows its
saved snapshot.

## Data policies

These are decisions, each with a test. Changing one changes what the published numbers mean.

- **Latest reading** (`latest_readings`): the whole stored row from the newest poll that included the
  series. A newer "Update Pending" or "Lanes Closed" row replaces an older number; nothing is carried
  over. Ties on the fetch time (a re-run) go to the later `run_id`.
- **Readings without an update time**: CBP publishes closed, pending and n/a lanes with no update time.
  They are facts too, timed by their fetch (`time_basis = 'fetch'`, `reading_at`), one per poll.
- **Repeated fetches and corrections** (`fct_wait_readings`): fetches of one source update are one row,
  keeping the first and last fetch and the count. When an agency changes a value under an unchanged
  update time (CBP did, 2 of 4,124 updates by 2026-11-14), the later value is kept and `revised` is true.
- **Quality** (`stg_readings.quality_issue`, `reading_quality`): a stored row with a category outside the
  contract, a delay outside 0–720 minutes, an update time that doesn't parse, or a stamp over a day
  ahead of its fetch stays in the snapshots and in staging but is left out of every mart. Delays of
  241–720 minutes are unusual but kept (a warning). Nothing is clipped or deleted.
- **Chart window and gates**: the by-hour aggregate covers the last `recent_days` (28, in
  `dbt_project.yml`). The page draws an hour when it has estimates on 3 local dates, solid at 7, with a
  90th-percentile band at 14 (`CHART` in `export/__main__.py`, published in the summary). These are
  display rules about how much history a point rests on, not confidence levels. `valid_days` counts
  dates with an estimate; `days` also counts dates when the lane was only closed.
- **Freshness**: a source's lag is the median age of its updates at the last fetch, never negative
  (a stamp ahead of the fetch counts as 0 and is counted separately). The page marks a reading or a run
  stale after 3 hours; that number is an estimate, and is deliberately not tied to how often GitHub
  happens to run the job.
- **Published-file retention**: each export carries forward only the files named by the manifests of
  the last 6 hours (always the previous one, at most 12), listed in `retained.json`. A page opened
  before a deploy can still fetch its files; older generations are not copied. The snapshots under
  `snapshots/` are never touched by this.

## Schema

One row per crossing × direction × lane group per run: `run_id`, `schema_version`, `fetched_at`,
`source`, `source_crossing_name`, `source_location`, `cbp_port_number`, `port_status`, `direction`
(`to_canada`, `to_us`), `lane` (`travellers`, `commercial`), `lane_type` (`standard`, `nexus_sentri`,
`fast`, `ready`), `status_raw`, `delay_min`, `is_open`, `lanes_open`, `source_updated_raw`,
`source_tz_abbrev`. `ingest/schema.py` checks every parsed row against this before a run is written.
Raise `schema_version` when a column is added.

The export's contract with the page is `export/contract.py` (the page applies the same rules in
`web/app.js` before drawing anything). Adding a field keeps `schema_version` 1; removing or re-meaning
one the page reads raises it, and the page then shows its saved snapshot until it is updated.

`dbt/seeds/dim_crossing.csv` maps the names in each feed to one `crossing_id`, with a time zone for
each side (`cbsa_iana_zone`, `cbp_iana_zone`). Crossings whose pairing isn't stated in the feeds stay
one-sided.

## Running it locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                       # parsers, checks, dbt on fixtures, export, retention, recovery
.venv/bin/python -m ingest --run-id local-1 --fixtures
cd dbt && ../.venv/bin/dbt build --profiles-dir . --vars "{run_id: local-1}"
```

The page tests need Node and Playwright with Chromium, and an export to show:

```sh
.venv/bin/python -m tests.fixture_store --datastore datastore        # a month of replayed fixture runs (test data)
(cd dbt && ../.venv/bin/dbt build --profiles-dir . --vars "{run_id: fx-2026111418, datastore: ../datastore}" --exclude tag:freshness)
.venv/bin/python -m export --run-id fx-2026111418 --generated-at 2026-11-14T18:30:00Z
node web/test/page.mjs public/data/v1     # offline: states, freshness, chart, snapshot
node web/test/sql.mjs public/data/v1      # needs jsDelivr and extensions.duckdb.org: the SQL console with real DuckDB-Wasm
```

## Operations

- **Quarantine a bad snapshot:** add its path on the `data` branch (`snapshots/...`) and a reason to
  `dbt/seeds/excluded_snapshots.csv`. Staging skips it; the `data` branch isn't rewritten. Snapshots are
  stored before the build, so a snapshot that breaks a model is kept and can be inspected; rows with a
  known quality issue are already left out of the marts without quarantining anything.
- **Refresh the page's saved snapshot** (`web/fallback/`, a real export of the featured crossings): check
  out the `data` branch as `datastore/`, build, and export with `--snapshot`:
  ```sh
  git fetch --depth 1 origin data && git worktree add datastore FETCH_HEAD
  (cd dbt && ../.venv/bin/dbt build --profiles-dir . --vars "{run_id: '', datastore: ../datastore}" --exclude tag:freshness)
  .venv/bin/python -m export --run-id "snapshot-of-<newest run id>" --data-sha "$(git -C datastore rev-parse --short HEAD)" \
    --git-sha "$(git rev-parse HEAD)" --out /tmp/export --previous /tmp/none --snapshot web/fallback
  .venv/bin/python -m export.snapshot_check web/fallback --max-age-days 14
  ```
  Then re-sync the site's copy (its README has the rsync line).
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
here (everything but `web/test/`). It reads `manifest.json`, `status.json` and the summary; DuckDB-Wasm
loads only when the visitor asks for the SQL console. If the live files can't be loaded or fail the
contract, it shows `web/fallback/`, labelled as a saved snapshot, and the console runs on that.

Deploy order when the export and the page change together: merge here first and let one run publish
the new export, then sync the site. The page tolerates an older export (fields it doesn't find fall
back), but its questions use columns the older export doesn't have.

## License

Code: MIT. Data: see `LICENSE-DATA.md`.
