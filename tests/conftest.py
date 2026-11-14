"""A multi-week datastore, its dbt build and its export, built once for the tests that need realistic volume."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import fixture_store

ROOT = Path(__file__).resolve().parent.parent
DBT = Path(sys.executable).with_name("dbt")


def dbt_build(work, run_id, datastore=None, exclude=("tag:freshness",)):
    env = {**os.environ, "BWT_DB": str(work / "bwt.duckdb")}
    args = [str(DBT), "build", "--profiles-dir", ".", "--target-path", str(work / "target"),
            "--vars", json.dumps({"datastore": str(datastore or work / "ds"), "run_id": run_id}), "--exclude", *exclude]
    p = subprocess.run(args, cwd=ROOT / "dbt", env=env, capture_output=True, text=True)
    results = json.loads((work / "target" / "run_results.json").read_text())["results"]
    return p, results


@pytest.fixture(scope="session")
def multiweek(tmp_path_factory):
    """30 days of replayed fixture runs (tests/fixture_store.py), built and exported."""
    from export import __main__ as export
    work = tmp_path_factory.mktemp("multiweek")
    runs = fixture_store.build(work / "ds")
    run_id = "fx-" + runs[-1][:13].replace("-", "").replace("T", "")
    p, _ = dbt_build(work, run_id)
    assert p.returncode == 0, p.stdout[-3000:]
    out = work / "public" / "data" / "v1"
    args = ["--run-id", run_id, "--db", str(work / "bwt.duckdb"), "--dbt-target", str(work / "target"),
            "--datastore", str(work / "ds"), "--generated-at", "2026-11-14T18:30:00Z"]
    assert export.main(args + ["--out", str(out), "--previous", str(work / "none"), "--snapshot", str(work / "bundle")]) == 0
    return SimpleNamespace(work=work, out=out, bundle=work / "bundle", run_id=run_id, runs=runs, export_args=args)
