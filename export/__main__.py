"""Writes public/data/v1/: content-hashed data files, summary, compiled SQL, manifest, status, index.html.

python -m export --run-id ID [--db dbt/target/bwt.duckdb] [--dbt-target dbt/target] [--out public/data/v1]
                 [--previous datastore/published/data/v1] [--run-url URL] [--git-sha SHA] [--data-sha SHA]
                 [--run-seconds N] [--snapshot-bytes N] [--datastore datastore]
                 [--retain-hours 6] [--retain-max 12] [--snapshot web/fallback]

--snapshot also writes the page's saved fallback: the same export limited to the featured crossings,
small enough to commit, complete enough for the SQL console to run on it.
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from .contract import SCHEMA_VERSION, validate

TABLES = ["dim_crossing", "fct_wait_readings", "fct_wait_readings_recent", "latest_readings", "agg_wait_by_hour",
          "agg_wait_by_weekday_hour", "fct_service_standard_monthly", "stg_cbsa_land_monthly"]
SQL_MODELS = ["agg_wait_by_hour", "agg_wait_by_weekday_hour", "fct_service_standard_monthly"]
SOURCES = {
    "cbsa": {"url": "https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv",
             "licence": "Open Government Licence – Canada", "licence_url": "https://open.canada.ca/en/open-government-licence-canada",
             "attribution": "Contains information licensed under the Open Government Licence – Canada."},
    "cbp": {"url": "https://bwt.cbp.gov/xml/bwt.xml", "licence": "Public domain (U.S. government work)",
            "licence_url": "https://www.cbp.gov/site-policy-notices/copyright",
            "attribution": "Source: U.S. Customs and Border Protection"},
}
# The browser re-runs agg_wait_by_hour's compiled SQL over the published recent file and compares these.
CHECK_SQL = "with t as (\n{sql}\n) select count(*) as n, sum(t.n) as sum, md5(string_agg(t::varchar, '|' order by t::varchar)) as md5 from t"
# The by-hour chart's display rules, in local dates that have an estimate for the hour (valid_days). They say
# how much history a point rests on; they are not confidence levels. The page, its table and the console's
# first question all read them from the summary, so they cannot drift apart.
CHART = {"min_days_point": 3, "min_days_solid": 7, "min_days_band": 14}
# A source is 'warn' when the median age of its updates at the last fetch passes the first number, 'error'
# past the second (minutes; estimated, the same numbers as the freshness tests in dbt/models/schema.yml).
LAG_WARN, LAG_ERROR = 120, 360
# What each warning means, for a reader who has not seen the dbt project.
WARNING_TEXT = {
    "warn_source_updated_ahead": "readings stamped more than 15 minutes after their fetch (CBP stamps the coming hour)",
    "warn_tz_abbrev_matches_zone": "readings whose time-zone abbreviation disagrees with the crossing's zone; the zone decides",
    "warn_unknown_status_raw": "status values the parsers have not seen before",
    "warn_history_metadata_age": "CBSA has not updated its monthly history file in over 120 days",
    "warn_history_delay_0_720": "stored readings with a delay outside 0-720 minutes; kept in the snapshots, left out of the tables",
    "warn_delay_above_240": "estimates above 240 minutes; unusual, kept",
    "warn_featured_series_missing": "a Windsor–Detroit crossing was missing from a feed in the last run",
    "warn_estimate_without_update_time": "estimates published without an update time; timed by their fetch",
    "warn_history_schema_version": "stored rows written under another row contract",
    "freshness_warn_cbsa": "CBSA's updates were typically more than 2 hours old when fetched",
    "freshness_warn_cbp": "CBP's updates were typically more than 2 hours old when fetched",
    "unmatched_crossings": "crossing names with no row in the crosswalk",
}
FEATURED = "(select crossing_id from main.dim_crossing where featured)"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashed_copy(src, out, name, ext):
    digest = sha256(src)
    dest = out / f"{name}.{digest[:8]}.{ext}"
    shutil.copyfile(src, dest)
    return dest, digest


def rebuild_check(sql, recent_file):
    con = duckdb.connect()
    con.execute("set TimeZone = 'UTC'")
    con.execute("attach ':memory:' as bwt")
    con.execute(f"create view bwt.main.fct_wait_readings_recent as select * from read_parquet('{recent_file}')")
    n, total, md5 = con.execute(CHECK_SQL.format(sql=sql)).fetchone()
    return {"n": n, "sum": int(total or 0), "md5": md5}


def test_counts(run_results):
    counts, warnings, details = {"pass": 0, "warn": 0, "error": 0, "skip": 0}, [], []
    for path in run_results:
        if not Path(path).exists():
            continue
        for r in json.loads(Path(path).read_text())["results"]:
            if not r["unique_id"].startswith(("test.", "unit_test.")):
                continue
            st = {"fail": "error"}.get(r["status"], r["status"])
            counts[st] = counts.get(st, 0) + 1
            if st == "warn":
                name = r["unique_id"].split(".")[2]
                warnings.append(f"{name}: {r.get('failures')} rows")
                details.append({"name": name, "rows": r.get("failures"), "text": WARNING_TEXT.get(name)})
    return counts, warnings, details


def recent_days(project):
    """The window dbt built fct_wait_readings_recent with (dbt_project.yml is the one place it is set)."""
    import yaml
    return int(yaml.safe_load(Path(project).read_text())["vars"]["recent_days"])


def scope_filter(table, featured_only):
    if not featured_only:
        return ""
    if table == "dim_crossing":
        return " where featured"
    if table == "stg_cbsa_land_monthly":
        return " where port_of_entry in (select cbsa_history_name from main.dim_crossing where featured)"
    return f" where crossing_id in {FEATURED}"


def source_health(con):
    """Per source, from its last fetch: how old the updates were, across all its rows rather than the newest one."""
    out = {}
    for s, meta in SOURCES.items():
        age = "greatest(date_diff('minute', source_updated_at, fetched_at), 0)"
        (last_fetch, newest, n_rows, crossings, timed, ahead, median_age, oldest, old) = con.execute(f"""
            with last as (select * from main.int_readings_matched where source = $1
                          and fetched_at = (select max(fetched_at) from main.int_readings_matched where source = $1))
            select max(fetched_at), max(source_updated_at), count(*), count(distinct crossing_id), count(source_updated_at),
                   count(*) filter (where source_updated_at > fetched_at), median({age}), max({age}),
                   count(*) filter (where {age} > {LAG_WARN})
            from last""", [s]).fetchone()
        lag = None if median_age is None else round(median_age)
        out[s] = {**meta, "last_fetched_at": str(last_fetch), "newest_source_updated_at": str(newest),
                  # lag_minutes used to be fetch minus the newest update, which one fresh crossing could carry
                  # and a coming-hour stamp could turn negative. It is now the median age, never below 0.
                  "lag_minutes": lag,
                  "freshness": None if lag is None else "error" if lag > LAG_ERROR else "warn" if lag > LAG_WARN else "pass",
                  "last_run": {"crossings": crossings, "rows": n_rows, "timed_rows": timed, "stamped_ahead": ahead,
                               "median_age_minutes": lag, "oldest_age_minutes": oldest, "older_than_2h": old}}
    return out


def cadence(con):
    """The schedule actually achieved: GitHub runs scheduled workflows best-effort."""
    runs_7d, median_gap, max_gap, runs_24h = con.execute("""
        with r as (select *, (select max(fetched_at) from main.pipeline_runs) as newest from main.pipeline_runs)
        select count(*) filter (where fetched_at > newest - interval 7 day),
               median(minutes_since_previous) filter (where fetched_at > newest - interval 7 day),
               max(minutes_since_previous) filter (where fetched_at > newest - interval 7 day),
               count(*) filter (where fetched_at > newest - interval 24 hour)
        from r""").fetchone()
    return {"runs_24h": runs_24h, "runs_7d": runs_7d,
            "median_gap_minutes_7d": None if median_gap is None else round(median_gap), "max_gap_minutes_7d": max_gap}


def retained_files(manifest):
    return sorted({f["url"] for f in manifest["files"].values()})


def carry_over(prev, out, generation, retain_hours, retain_max):
    """Copies forward only the files that the retained earlier manifests name, and returns the new index.

    A page that loaded before this deploy holds an older manifest and may still ask for its files (the SQL
    console loads them on click). The index keeps the generations of the last retain_hours, the one before
    this run whatever its age, and never more than retain_max; a file no retained generation names is not
    copied, so the published directory stays bounded. Content-hashed files shared between generations are
    stored once. The snapshots on the data branch are never touched by this.
    """
    prev = Path(prev)
    index = []
    if (prev / "retained.json").exists():
        index = json.loads((prev / "retained.json").read_text())
    elif (prev / "manifest.json").exists():  # an export from before the index existed: keep its own files
        m = json.loads((prev / "manifest.json").read_text())
        index = [{"run_id": m.get("run_id"), "generated_at": m.get("generated_at"), "files": retained_files(m)}]
    cutoff = datetime.fromisoformat(generation["generated_at"].replace("Z", "+00:00")) - timedelta(hours=retain_hours)
    keep = []
    for i, g in enumerate(g for g in index if g.get("run_id") != generation["run_id"]):
        try:
            recent = datetime.fromisoformat(str(g["generated_at"]).replace("Z", "+00:00")) >= cutoff
        except (KeyError, ValueError):
            recent = False
        if (i == 0 or recent) and len(keep) < retain_max - 1:
            keep.append(g)
    for g in keep:
        for rel in g["files"]:
            src, dest = prev / rel, out / rel
            if ".." in Path(rel).parts or dest.exists() or not src.is_file():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
    return [generation] + keep


def write_export(con, a, out, featured_only=False):
    """Writes one self-consistent data directory and returns its manifest."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "sql").mkdir(parents=True)
    tmp = out / "_tmp"
    tmp.mkdir()

    files = {}
    for t in TABLES:
        order = " order by crossing_id, reading_at" if t.startswith("fct_wait_readings") else ""
        where = scope_filter(t, featured_only)
        src = tmp / f"{t}.parquet"
        con.execute(f"copy (select * from main.{t}{where}{order}) to '{src}' (format parquet, compression zstd)")
        dest, digest = hashed_copy(src, out, t, "parquet")
        files[t] = {"url": dest.name, "sha256": digest, "rows": con.execute(f"select count(*) from main.{t}{where}").fetchone()[0],
                    "bytes": dest.stat().st_size}
    compiled = Path(a.dbt_target) / "compiled" / "border_waits" / "models" / "marts"
    for m in SQL_MODELS:
        dest, digest = hashed_copy(compiled / f"{m}.sql", out / "sql", m, "sql")
        files[f"sql/{m}"] = {"url": f"sql/{dest.name}", "sha256": digest, "rows": None, "bytes": dest.stat().st_size}

    rows = lambda q: [dict(zip([d[0] for d in con.description], r)) for r in con.execute(q).fetchall()]
    window_end, days_collected = con.execute(f"""
        select (select max(fetched_at) from main.fct_wait_readings),
               count(distinct cast(timezone(iana_zone, reading_at) as date))
        from main.fct_wait_readings_recent where crossing_id in {FEATURED}""").fetchone()
    days = recent_days(a.dbt_project)
    summary = {
        "run_id": a.run_id,
        "crossings": rows("select crossing_id, display_name from main.dim_crossing where featured order by crossing_id"),
        # One whole row per series from the newest poll that included it (dbt: latest_readings). observed_at is
        # that poll; source_updated_at is the agency's own stamp and is null where the agency gives none.
        "latest": rows(f"""select crossing_id, direction, lane, source, status_raw, delay_min, is_open,
            source_updated_at::varchar as source_updated_at, observed_at::varchar as observed_at
            from main.latest_readings where crossing_id in {FEATURED} order by crossing_id, direction, lane"""),
        "by_hour": rows(f"select * from main.agg_wait_by_hour where crossing_id in {FEATURED} order by all"),
        "chart": {"window_days": days, "window_end": None if window_end is None else str(window_end),
                  "window_start": None if window_end is None else str(window_end - timedelta(days=days)),
                  "days_with_readings": days_collected, **CHART},
    }
    summary_name = "summary.json" if featured_only else f"summary.{a.run_id}.json"
    summary_path = out / summary_name
    summary_path.write_text(json.dumps(summary, separators=(",", ":"), default=str))
    files["summary"] = {"url": summary_path.name, "sha256": sha256(summary_path), "rows": None, "bytes": summary_path.stat().st_size}

    hist = sorted((Path(a.datastore) / "history" / "cbsa_land").glob("*.csv"))
    sources = source_health(con)
    sources["cbsa_history"] = {"url": "https://open.canada.ca/data/en/dataset/000fe5aa-1d77-42d1-bfe7-458c51dacfef",
                               "licence": SOURCES["cbsa"]["licence"], "attribution": SOURCES["cbsa"]["attribution"],
                               "metadata_modified": hist[-1].stem if hist else None}
    counts, warnings, details = test_counts([Path(a.dbt_target) / "run_results.json", a.freshness_results])
    recent_sql = (compiled / "agg_wait_by_hour.sql").read_text()
    datastore = Path(a.datastore)
    fetch_timed, revised = con.execute(
        "select count(*) filter (where time_basis = 'fetch'), count(*) filter (where revised) from main.fct_wait_readings").fetchone()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": a.generated_at,
        "run_id": a.run_id, "run_url": a.run_url, "git_sha": a.git_sha, "data_sha": a.data_sha,
        # the earliest stored reading: what the page's "Collecting data since" line shows
        "collecting_since": str(con.execute("select min(fetched_at) from main.fct_wait_readings").fetchone()[0]),
        "duckdb_version": duckdb.__version__, "dbt_version": _dbt_version(),
        "files": files,
        "sources": sources,
        "cadence": cadence(con),
        "tests": {**counts, "warnings": warnings, "details": details},
        # Stored rows the tables leave out, by reason (dbt: reading_quality), and how many readings rest on
        # the two documented policies: timed by their fetch, and revised under an unchanged source time.
        "quality": {"excluded": rows("select source, quality_issue as reason, stored_rows as rows, runs from main.reading_quality order by all"),
                    "fetch_timed_readings": fetch_timed, "revised_readings": revised},
        "cost": {"run_seconds": a.run_seconds, "snapshot_bytes_added": a.snapshot_bytes,
                 "data_branch_bytes": sum(p.stat().st_size for p in datastore.rglob("*") if p.is_file() and ".git" not in p.parts)
                 if datastore.exists() else None},
        "rebuild_check": {"model": "agg_wait_by_hour", "sql": files["sql/agg_wait_by_hour"]["url"],
                          "input": files["fct_wait_readings_recent"]["url"], "check_sql": CHECK_SQL,
                          "expected": rebuild_check(recent_sql, out / files["fct_wait_readings_recent"]["url"])},
    }
    if featured_only:
        manifest["sample"] = {"scope": "featured", "captured_at": a.generated_at,
                              "note": "A saved copy of one real export, limited to the three Windsor–Detroit crossings."}
    shutil.rmtree(tmp)
    validate(manifest, summary)  # nothing the page would reject gets published
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m export")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", default="dbt/target/bwt.duckdb")
    ap.add_argument("--dbt-target", default="dbt/target")
    ap.add_argument("--dbt-project", default=str(Path(__file__).resolve().parent.parent / "dbt" / "dbt_project.yml"))
    ap.add_argument("--freshness-results", default="dbt/target-freshness/run_results.json")
    ap.add_argument("--out", default="public/data/v1")
    ap.add_argument("--previous", default="datastore/published/data/v1")
    ap.add_argument("--datastore", default="datastore")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--git-sha", default="")
    ap.add_argument("--data-sha", default="")
    ap.add_argument("--run-seconds", type=float, default=None)
    ap.add_argument("--snapshot-bytes", type=int, default=None)
    ap.add_argument("--retain-hours", type=float, default=6, help="keep earlier generations' files this long")
    ap.add_argument("--retain-max", type=int, default=12, help="and never more than this many generations")
    ap.add_argument("--generated-at", help="override the export time (tests)")
    ap.add_argument("--snapshot", help="also write the page's saved fallback here (featured crossings only)")
    a = ap.parse_args(argv)
    a.generated_at = a.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = Path(a.out)
    con = duckdb.connect(a.db, read_only=True)
    con.execute("set TimeZone = 'UTC'")

    manifest = write_export(con, a, out)
    generation = {"run_id": a.run_id, "generated_at": a.generated_at, "files": retained_files(manifest)}
    index = carry_over(a.previous, out, generation, a.retain_hours, a.retain_max)
    manifest["retention"] = {"hours": a.retain_hours, "max_generations": a.retain_max, "generations": len(index)}
    (out / "retained.json").write_text(json.dumps(index, indent=1))
    status = {"run_id": a.run_id, "time": a.generated_at, "result": "success"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    (out / "status.json").write_text(json.dumps(status, indent=1))
    (out / "index.html").write_text(INDEX)
    if a.snapshot:
        snap = Path(a.snapshot)
        sample = write_export(con, a, snap, featured_only=True)
        (snap / "manifest.json").write_text(json.dumps(sample, indent=1, default=str))
        (snap / "status.json").write_text(json.dumps(status, indent=1))
    files = manifest["files"]
    print(f"exported {len(files)} files to {out}; summary {files['summary']['bytes']} B; "
          f"{len(index)} generation(s) retained; rebuild check {manifest['rebuild_check']['expected']}")
    return 0


def _dbt_version():
    try:
        from importlib.metadata import version
        return version("dbt-core")
    except Exception:
        return None


INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>border-waits data</title></head>
<body>
<p>These are the data files for the border-waits page: <a href="https://brettadams0.github.io/border-waits/">https://brettadams0.github.io/border-waits/</a>. <a href="manifest.json">manifest.json</a> lists them.</p>
<p>Contains information licensed under the <a href="https://open.canada.ca/en/open-government-licence-canada">Open Government Licence – Canada</a>.</p>
<p>Source: U.S. Customs and Border Protection</p>
</body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
