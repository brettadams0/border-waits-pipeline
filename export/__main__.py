"""Writes public/data/v1/: content-hashed data files, summary, compiled SQL, manifest, status, index.html.

python -m export --run-id ID [--db dbt/target/bwt.duckdb] [--dbt-target dbt/target] [--out public/data/v1]
                 [--previous datastore/published/data/v1] [--run-url URL] [--git-sha SHA] [--data-sha SHA]
                 [--run-seconds N] [--snapshot-bytes N] [--datastore datastore]
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

TABLES = ["dim_crossing", "fct_wait_readings", "fct_wait_readings_recent", "agg_wait_by_hour",
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
    counts, warnings = {"pass": 0, "warn": 0, "error": 0, "skip": 0}, []
    for path in run_results:
        if not Path(path).exists():
            continue
        for r in json.loads(Path(path).read_text())["results"]:
            if not r["unique_id"].startswith(("test.", "unit_test.")):
                continue
            st = {"fail": "error"}.get(r["status"], r["status"])
            counts[st] = counts.get(st, 0) + 1
            if st == "warn":
                warnings.append(f"{r['unique_id'].split('.')[2]}: {r.get('failures')} rows")
    return counts, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m export")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", default="dbt/target/bwt.duckdb")
    ap.add_argument("--dbt-target", default="dbt/target")
    ap.add_argument("--freshness-results", default="dbt/target-freshness/run_results.json")
    ap.add_argument("--out", default="public/data/v1")
    ap.add_argument("--previous", default="datastore/published/data/v1")
    ap.add_argument("--datastore", default="datastore")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--git-sha", default="")
    ap.add_argument("--data-sha", default="")
    ap.add_argument("--run-seconds", type=float, default=None)
    ap.add_argument("--snapshot-bytes", type=int, default=None)
    ap.add_argument("--snapshot", help="also copy manifest.json and the summary here (the page's fallback/)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "sql").mkdir(parents=True)
    con = duckdb.connect(a.db, read_only=True)
    con.execute("set TimeZone = 'UTC'")
    tmp = out / "_tmp"
    tmp.mkdir()

    files = {}
    for t in TABLES:
        order = " order by crossing_id, source_updated_at" if t.startswith("fct_wait_readings") else ""
        src = tmp / f"{t}.parquet"
        con.execute(f"copy (select * from main.{t}{order}) to '{src}' (format parquet, compression zstd)")
        dest, digest = hashed_copy(src, out, t, "parquet")
        files[t] = {"url": dest.name, "sha256": digest, "rows": con.execute(f"select count(*) from main.{t}").fetchone()[0],
                    "bytes": dest.stat().st_size}
    compiled = Path(a.dbt_target) / "compiled" / "border_waits" / "models" / "marts"
    for m in SQL_MODELS:
        dest, digest = hashed_copy(compiled / f"{m}.sql", out / "sql", m, "sql")
        files[f"sql/{m}"] = {"url": f"sql/{dest.name}", "sha256": digest, "rows": None, "bytes": dest.stat().st_size}

    featured = "crossing_id in (select crossing_id from main.dim_crossing where featured)"
    rows = lambda q: [dict(zip([d[0] for d in con.description], r)) for r in con.execute(q).fetchall()]
    summary = {
        "run_id": a.run_id,
        "crossings": rows("select crossing_id, display_name from main.dim_crossing where featured order by crossing_id"),
        "latest": rows(f"""select crossing_id, direction, lane, arg_max(delay_min, source_updated_at) as delay_min,
            arg_max(is_open, source_updated_at) as is_open, arg_max(status_raw, source_updated_at) as status_raw,
            max(source_updated_at)::varchar as source_updated_at from main.fct_wait_readings where {featured} group by all order by all"""),
        "last_48h": rows(f"""select crossing_id, direction, lane, source_updated_at::varchar as source_updated_at, delay_min, is_open
            from main.fct_wait_readings where {featured}
            and source_updated_at >= (select max(fetched_at) from main.fct_wait_readings) - interval 48 hour order by all"""),
        "by_hour": rows(f"select * from main.agg_wait_by_hour where {featured} order by all"),
    }
    summary_path = out / f"summary.{a.run_id}.json"
    summary_path.write_text(json.dumps(summary, separators=(",", ":"), default=str))
    files["summary"] = {"url": summary_path.name, "sha256": sha256(summary_path), "rows": None, "bytes": summary_path.stat().st_size}

    sources = {}
    for s, meta in SOURCES.items():
        last_fetch, newest = con.execute(
            "select max(fetched_at), max(source_updated_at) from main.fct_wait_readings where source = ?", [s]).fetchone()
        lag = round((last_fetch - newest).total_seconds() / 60) if last_fetch and newest else None
        sources[s] = {**meta, "last_fetched_at": str(last_fetch), "newest_source_updated_at": str(newest), "lag_minutes": lag,
                      "freshness": None if lag is None else "error" if lag > 360 else "warn" if lag > 120 else "pass"}
    hist = sorted((Path(a.datastore) / "history" / "cbsa_land").glob("*.csv"))
    sources["cbsa_history"] = {"url": "https://open.canada.ca/data/en/dataset/000fe5aa-1d77-42d1-bfe7-458c51dacfef",
                               "licence": SOURCES["cbsa"]["licence"], "attribution": SOURCES["cbsa"]["attribution"],
                               "metadata_modified": hist[-1].stem if hist else None}
    counts, warnings = test_counts([Path(a.dbt_target) / "run_results.json", a.freshness_results])
    recent_sql = (compiled / "agg_wait_by_hour.sql").read_text()
    datastore = Path(a.datastore)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": a.run_id, "run_url": a.run_url, "git_sha": a.git_sha, "data_sha": a.data_sha,
        "duckdb_version": duckdb.__version__, "dbt_version": _dbt_version(),
        "files": files,
        "sources": sources,
        "tests": {**counts, "warnings": warnings},
        "cost": {"run_seconds": a.run_seconds, "snapshot_bytes_added": a.snapshot_bytes,
                 "data_branch_bytes": sum(p.stat().st_size for p in datastore.rglob("*") if p.is_file() and ".git" not in p.parts)
                 if datastore.exists() else None},
        "rebuild_check": {"model": "agg_wait_by_hour", "sql": files["sql/agg_wait_by_hour"]["url"],
                          "input": files["fct_wait_readings_recent"]["url"], "check_sql": CHECK_SQL,
                          "expected": rebuild_check(recent_sql, out / files["fct_wait_readings_recent"]["url"])},
    }
    shutil.rmtree(tmp)
    # keep the previous run's data files, so a SQL session that started before this deploy can finish
    prev = Path(a.previous)
    if prev.exists():
        for p in list(prev.glob("*.parquet")) + list(prev.glob("summary.*.json")) + list((prev / "sql").glob("*.sql")):
            dest = out / p.relative_to(prev)
            if not dest.exists():
                shutil.copyfile(p, dest)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    (out / "status.json").write_text(json.dumps({"run_id": a.run_id, "time": manifest["generated_at"], "result": "success"}, indent=1))
    (out / "index.html").write_text(INDEX)
    if a.snapshot:
        snap = Path(a.snapshot)
        snap.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / "manifest.json", snap / "manifest.json")
        shutil.copyfile(summary_path, snap / "summary.json")
    print(f"exported {len(files)} files to {out}; summary {files['summary']['bytes']} B; rebuild check {manifest['rebuild_check']['expected']}")
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
