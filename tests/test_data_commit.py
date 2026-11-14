"""D12: the run's snapshots are stored before dbt or the export can fail (scripts/commit-data.sh).

A bare repository stands in for GitHub's `data` branch and a shallow clone for the workflow's checkout,
so the ordering the workflow relies on is exercised without dispatching it.
"""
import os
import subprocess
from pathlib import Path

import pytest

from ingest import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "commit-data.sh"
ID = ["-c", "user.name=test", "-c", "user.email=test@example.test"]


def git(cwd, *args):
    return subprocess.run(["git", *ID, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit_data(checkout, run_id, stage, *paths):
    return subprocess.run([str(SCRIPT), stage, *paths], cwd=checkout.parent, capture_output=True, text=True,
                          env={**os.environ, "RUN_ID": run_id, "DATASTORE": str(checkout)})


@pytest.fixture
def data_branch(tmp_path):
    """origin with a `data` branch that holds one earlier good export, and the workflow's shallow checkout of it."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "data", str(origin)], check=True)
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(origin), str(seed))
    (seed / "published" / "data" / "v1").mkdir(parents=True)
    (seed / "published" / "data" / "v1" / "manifest.json").write_text('{"run_id": "last-good"}')
    (seed / "published" / "data" / "v1" / "fct.old.parquet").write_text("old")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "publish last-good")
    git(seed, "push", "-q", "origin", "HEAD:data")
    checkout = tmp_path / "datastore"
    git(tmp_path, "clone", "-q", "--depth", "1", "--branch", "data", origin.as_uri(), str(checkout))
    return origin, checkout


def remote_files(origin):
    return set(git(origin, "ls-tree", "-r", "--name-only", "data").splitlines())


def ingest(checkout, run_id, fetched_at):
    assert cli.main(["--run-id", run_id, "--fixtures", "--datastore", str(checkout),
                     "--raw-dir", str(checkout.parent / "raw"), "--fetched-at", fetched_at]) == 0


def test_snapshots_survive_a_failed_build_and_published_stays_last_good(data_branch):
    origin, checkout = data_branch
    ingest(checkout, "5-1", "2026-10-27T17:26:20Z")
    r = commit_data(checkout, "5-1", "ingest", "snapshots", "raw", "history")     # history/ does not exist yet: skipped, not an error
    assert r.returncode == 0, r.stderr
    # the build now fails part-way: a half-written export and a stray file are lying in the checkout
    (checkout / "published" / "data" / "v1" / "manifest.json").write_text('{"run_id": "5-1, half written"}')
    (checkout / "published" / "data" / "v1" / "fct.new.parquet").write_text("partial")
    (checkout / "bwt.duckdb.tmp").write_text("scratch")
    stored = remote_files(origin)
    assert {"snapshots/source=cbsa/date=2026-10-27/172620.parquet", "snapshots/source=cbp/date=2026-10-27/172620.parquet",
            "raw/source=cbsa/date=2026-10-27/172620.csv.gz"} <= stored
    assert "published/data/v1/fct.new.parquet" not in stored and "bwt.duckdb.tmp" not in stored
    assert git(origin, "show", "data:published/data/v1/manifest.json") == '{"run_id": "last-good"}'
    assert git(origin, "log", "-1", "--format=%s", "data") == "ingest 5-1"


def test_a_retried_run_adds_its_own_snapshots_and_publish_replaces_the_export(data_branch):
    origin, checkout = data_branch
    ingest(checkout, "5-1", "2026-10-27T17:26:20Z")
    assert commit_data(checkout, "5-1", "ingest", "snapshots", "raw", "history").returncode == 0
    ingest(checkout, "5-2", "2026-10-27T17:41:03Z")                                # the re-run fetches again, a little later
    assert commit_data(checkout, "5-2", "ingest", "snapshots", "raw", "history").returncode == 0
    again = commit_data(checkout, "5-2", "ingest", "snapshots", "raw", "history")  # nothing new: no empty commit, no failure
    assert again.returncode == 0 and "nothing to commit" in again.stdout
    files = remote_files(origin)
    assert sum(1 for f in files if f.startswith("snapshots/")) == 4                # both attempts kept; dbt folds repeats of one update into one row
    # the export succeeds this time: published/ is replaced whole, old generation files go
    v1 = checkout / "published" / "data" / "v1"
    (v1 / "fct.old.parquet").unlink()
    (v1 / "manifest.json").write_text('{"run_id": "5-2"}')
    (v1 / "fct.new.parquet").write_text("new")
    assert commit_data(checkout, "5-2", "publish", "published").returncode == 0
    files = remote_files(origin)
    assert "published/data/v1/fct.new.parquet" in files and "published/data/v1/fct.old.parquet" not in files
    assert [s for s in git(origin, "log", "--format=%s", "data").splitlines()] == ["publish 5-2", "ingest 5-2", "ingest 5-1", "publish last-good"]


def test_a_conflicting_push_is_replayed_not_overwritten(data_branch, tmp_path):
    origin, checkout = data_branch
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(origin), str(other))
    (other / "snapshots" / "source=cbsa" / "date=2026-10-27").mkdir(parents=True)
    (other / "snapshots" / "source=cbsa" / "date=2026-10-27" / "160000.parquet").write_text("someone else's run")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "ingest 4-1")
    git(other, "push", "-q", "origin", "HEAD:data")
    ingest(checkout, "5-1", "2026-10-27T17:26:20Z")
    r = commit_data(checkout, "5-1", "ingest", "snapshots", "raw", "history")
    assert r.returncode == 0 and "rebasing" in r.stderr, r.stderr
    files = remote_files(origin)
    assert "snapshots/source=cbsa/date=2026-10-27/160000.parquet" in files and "snapshots/source=cbsa/date=2026-10-27/172620.parquet" in files


def test_run_id_is_required(data_branch):
    origin, checkout = data_branch
    ingest(checkout, "5-1", "2026-10-27T17:26:20Z")
    env = {k: v for k, v in os.environ.items() if k != "RUN_ID"}
    r = subprocess.run([str(SCRIPT), "ingest", "snapshots"], cwd=checkout.parent, capture_output=True, text=True, env={**env, "DATASTORE": str(checkout)})
    assert r.returncode != 0 and "snapshots/source=cbsa/date=2026-10-27/172620.parquet" not in remote_files(origin)
