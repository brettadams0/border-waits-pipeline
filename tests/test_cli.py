import gzip
from pathlib import Path

import duckdb

from ingest import __main__ as cli
from ingest import checks

T = "2026-10-27T17:26:20Z"


def test_fixture_run_writes_one_file_per_source(tmp_path):
    rc = cli.main(["--run-id", "7-1", "--fixtures", "--datastore", str(tmp_path / "ds"),
                   "--raw-dir", str(tmp_path / "raw"), "--fetched-at", T])
    assert rc == 0
    files = sorted(p.relative_to(tmp_path / "ds").as_posix() for p in (tmp_path / "ds").rglob("*.*"))
    assert files == ["raw/source=cbsa/date=2026-10-27/172620.csv.gz",
                     "snapshots/source=cbp/date=2026-10-27/172620.parquet",
                     "snapshots/source=cbsa/date=2026-10-27/172620.parquet"]
    raw = gzip.decompress((tmp_path / "ds" / files[0]).read_bytes())
    assert raw == (Path(__file__).resolve().parent.parent / "fixtures" / "cbsa-bwt-eng.csv").read_bytes()
    n = duckdb.sql(f"select count(*) from read_parquet('{tmp_path}/ds/snapshots/**/*.parquet', "
                   "hive_partitioning = true, union_by_name = true) where run_id = '7-1'").fetchone()[0]
    assert n == 210
    assert (tmp_path / "raw" / "cbp-bwt.xml.headers.json").exists()


def test_failed_checks_write_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "MIN_CROSSINGS", 1000)
    rc = cli.main(["--run-id", "8-1", "--fixtures", "--datastore", str(tmp_path / "ds"),
                   "--raw-dir", str(tmp_path / "raw"), "--fetched-at", T])
    assert rc == 1
    assert not (tmp_path / "ds").exists()
    assert (tmp_path / "raw" / "cbsa-bwt-eng.csv").exists()  # the raw artifact is still kept
