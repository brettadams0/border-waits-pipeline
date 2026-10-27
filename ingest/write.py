"""Writes one Parquet file per source per run, plus the gzipped raw CBSA CSV."""
import gzip
from datetime import datetime
from pathlib import Path

import duckdb

from .schema import COLUMNS, NAMES


def run_paths(datastore, source, fetched_at):
    t = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    part = f"source={source}/date={t:%Y-%m-%d}"
    return (Path(datastore) / "snapshots" / part / f"{t:%H%M%S}.parquet",
            Path(datastore) / "raw" / part / f"{t:%H%M%S}.csv.gz")


def write_parquet(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("set TimeZone = 'UTC'")
    con.execute("create table r (" + ", ".join(f'"{n}" {t}' for n, t in COLUMNS) + ")")
    if rows:
        con.executemany(f"insert into r values ({', '.join('?' * len(NAMES))})",
                        [[row[n] for n in NAMES] for row in rows])
    con.execute(f"copy r to '{path}' (format parquet, compression zstd)")
    con.close()


def write_run(rows_by_source, cbsa_raw, datastore, fetched_at):
    written = []
    for source, rows in rows_by_source.items():
        pq, raw = run_paths(datastore, source, fetched_at)
        write_parquet(rows, pq)
        written.append(pq)
        if source == "cbsa":
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(gzip.compress(cbsa_raw, mtime=0))
            written.append(raw)
    return written
