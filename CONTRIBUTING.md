# Contributing

The most useful contribution is a report that one of the feeds changed. CBSA and CBP publish
without notice, and every rule in `ingest/` and `dbt/models/staging/` exists because a feed did
something once. A new crossing name, a new time format or a reading that lands on the wrong hour
is worth an issue even without a fix — use the **feed changed** template.

## Setup

Python 3.13, which is what CI and the hourly pipeline run. No network is needed for the tests;
everything runs on the files in `fixtures/`.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## What CI runs

```sh
python -m pytest -q                                   # parsers, checks, dbt on fixtures, export

mkdir -p datastore/history/cbsa_land
cp fixtures/cbsa-history.csv "datastore/history/cbsa_land/2025-12-18T22:31:02.377918.csv"
python -m ingest --run-id ci-1 --fixtures
(cd dbt && dbt build --profiles-dir . --vars "{run_id: ci-1, datastore: ../datastore}" --exclude tag:freshness)
python -m export --run-id ci-1

npm install -g playwright@1.56.1 && playwright install --with-deps chromium
NODE_PATH="$(npm root -g)" node web/test/page.mjs public/data/v1   # the page, against that export
```

A pull request is ready when all of that passes locally.

## Rules that are easy to break

- **A feed quirk gets a fixture and a test in the same commit.** Take the raw response from the
  failing run's `raw-<run id>` artifact, cut it down to the rows that matter, and add it under
  `fixtures/` or as a dbt unit test in `dbt/models/unit_tests.yml`. A rule with no failing input
  behind it will be read as a guess.
- **Error-severity tests check the current run only.** Each one needs a warning copy over all of
  history, so one bad old snapshot cannot block every later deploy. A new error test without its
  warning copy will be sent back.
- **The `data` branch is never rewritten.** A bad snapshot is quarantined by adding its path and a
  reason to `dbt/seeds/excluded_snapshots.csv`.
- **A new column raises `schema_version`.**
- `web/` is copied into brettadams0.github.io, so it must keep working with no build step.

## Commits

Imperative, with the area as a prefix when one applies: `ingest:`, `dbt:`, `export:`, `web:`,
`ci:`, `pipeline:`. Say what the feed did, not only what the code does now — the commit that
handles CBP's coming-hour stamps names the run that failed on one.

## Data

Readings are licensed by CBSA and CBP, not by this repository. See [LICENSE-DATA.md](LICENSE-DATA.md)
before reusing anything from the `data` branch.
