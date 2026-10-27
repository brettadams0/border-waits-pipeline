"""dbt against fixture-built snapshots (needs the pinned dbt in the environment)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ingest import __main__ as cli
from ingest import cbsa
from ingest.write import run_paths, write_parquet

ROOT = Path(__file__).resolve().parent.parent
DBT = Path(sys.executable).with_name("dbt")


def build(tmp_path, run_id):
    env = {**os.environ, "BWT_DB": str(tmp_path / "bwt.duckdb")}
    args = [str(DBT), "build", "--profiles-dir", ".", "--target-path", str(tmp_path / "target"),
            "--vars", json.dumps({"datastore": str(tmp_path / "ds"), "run_id": run_id}), "--exclude", "tag:freshness"]
    p = subprocess.run(args, cwd=ROOT / "dbt", env=env, capture_output=True, text=True)
    results = json.loads((tmp_path / "target" / "run_results.json").read_text())["results"]
    status = {}
    for r in results:
        status[r["status"]] = status.get(r["status"], 0) + 1
    return p.returncode, status, results


def datastore(tmp_path):
    hist = tmp_path / "ds" / "history" / "cbsa_land"
    hist.mkdir(parents=True)
    shutil.copy(ROOT / "fixtures" / "cbsa-history.csv", hist / "2025-12-18T22:31:02.377918.csv")


def test_bad_old_snapshot_still_builds(tmp_path):
    datastore(tmp_path)
    # one bad historical snapshot: a delay outside 0-720
    old = cbsa.parse((ROOT / "fixtures" / "cbsa-bwt-eng.csv").read_bytes(), "100-1", "2026-10-26T17:17:00Z")
    old[0]["delay_min"] = 900
    write_parquet(old, run_paths(tmp_path / "ds", "cbsa", "2026-10-26T17:17:00Z")[0])
    # plus one good new run
    assert cli.main(["--run-id", "101-1", "--fixtures", "--datastore", str(tmp_path / "ds"),
                     "--raw-dir", str(tmp_path / "raw"), "--fetched-at", "2026-10-27T17:26:20Z"]) == 0
    rc, status, results = build(tmp_path, "101-1")
    assert rc == 0 and status.get("error", 0) == 0 and status.get("fail", 0) == 0, status
    warned = {r["unique_id"].split(".")[2] for r in results if r["status"] == "warn"}
    assert "warn_history_delay_0_720" in warned, warned


def test_bad_current_run_fails(tmp_path):
    datastore(tmp_path)
    bad = cbsa.parse((ROOT / "fixtures" / "cbsa-bwt-eng.csv").read_bytes(), "102-1", "2026-10-27T17:26:20Z")
    bad[0]["delay_min"] = 900
    write_parquet(bad, run_paths(tmp_path / "ds", "cbsa", "2026-10-27T17:26:20Z")[0])
    rc, status, _ = build(tmp_path, "102-1")
    assert rc != 0 and status.get("fail", 0) >= 1, status


def test_export_after_good_build(tmp_path):
    import hashlib
    from export import __main__ as export
    datastore(tmp_path)
    assert cli.main(["--run-id", "103-1", "--fixtures", "--datastore", str(tmp_path / "ds"),
                     "--raw-dir", str(tmp_path / "raw"), "--fetched-at", "2026-10-27T17:26:20Z"]) == 0
    rc, _, _ = build(tmp_path, "103-1")
    assert rc == 0
    out = tmp_path / "public" / "data" / "v1"
    assert export.main(["--run-id", "103-1", "--db", str(tmp_path / "bwt.duckdb"), "--dbt-target", str(tmp_path / "target"),
                        "--out", str(out), "--datastore", str(tmp_path / "ds"), "--previous", str(tmp_path / "none")]) == 0
    m = json.loads((out / "manifest.json").read_text())
    for name, f in m["files"].items():
        body = (out / f["url"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == f["sha256"], name
        assert f["sha256"][:8] in f["url"] or name == "summary", name
    assert m["files"]["summary"]["bytes"] <= 30_000
    assert m["tests"]["error"] == 0
    assert m["rebuild_check"]["expected"] == export.rebuild_check(
        (out / m["files"]["sql/agg_wait_by_hour"]["url"]).read_text(), out / m["files"]["fct_wait_readings_recent"]["url"])
    assert "Open Government Licence – Canada" in (out / "index.html").read_text()
