"""Builds a multi-week datastore from the recorded fixtures, for tests that need realistic volume.

The two fixture feeds are replayed as if fetched on many days. Each replayed run keeps the feeds'
real structure (crossings, lanes, closed and n/a lanes, zones) and restamps the update times
relative to its own fetch; open lanes get a deterministic daily wait pattern. About two runs in
three are dropped, like GitHub's scheduler does, so hours and days have gaps.

This is synthetic TEST data. It is never published: the page's saved snapshot is a real export.

python -m tests.fixture_store --datastore datastore [--days 30] [--end 2026-11-14T18:26:20Z]
"""
import argparse
import csv
import gzip
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ingest import cbp, cbsa
import duckdb

from ingest.checks import run_checks
from ingest.schema import COLUMNS, NAMES
from ingest.write import run_paths

ROOT = Path(__file__).resolve().parent.parent
END = "2026-11-14T18:26:20Z"


def _h(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _zones():
    seed = list(csv.DictReader(open(ROOT / "dbt" / "seeds" / "dim_crossing.csv", encoding="utf-8")))
    return ({r["cbsa_csv_name"]: r["cbsa_iana_zone"] for r in seed if r["cbsa_csv_name"]},
            {r["cbp_port_number"]: r["cbp_iana_zone"] for r in seed if r["cbp_port_number"]})


def _wait(key, local):
    """A plausible estimate in 5-minute steps: quiet nights, a morning and an afternoon peak, some noise."""
    base = 20 if local.hour in (7, 8, 16, 17) else 10 if 6 <= local.hour <= 19 else 0
    noise = _h(key, local.date(), local.hour) % 4 * 5
    return max(0, base + noise - 5) if base or _h(key, local.date()) % 3 == 0 else 0


def run_rows(fetched, cbsa_body, cbp_body, zones):
    stamp = fetched.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"fx-{fetched:%Y%m%d%H}"
    cbsa_zone, cbp_zone = zones
    out = {"cbsa": cbsa.parse(cbsa_body, run_id, stamp), "cbp": cbp.parse(cbp_body, run_id, stamp)}
    for r in out["cbsa"]:
        zone = cbsa_zone.get(r["source_crossing_name"])
        if not zone:
            continue
        # CBSA updates on its own clock: some minutes before the fetch, sometimes over an hour
        local = (fetched - timedelta(minutes=5 + _h(r["source_crossing_name"], stamp) % 70)).astimezone(ZoneInfo(zone))
        r["source_updated_raw"] = f"{local:%Y-%m-%d %H:%M} {local.tzname()}"
        r["source_tz_abbrev"] = local.tzname()
        if r["delay_min"] is not None:
            d = _wait(r["source_crossing_name"] + r["lane"], local)
            r["delay_min"], r["status_raw"] = d, "No Delay" if d == 0 else f"{d} minutes"
    for r in out["cbp"]:
        zone = cbp_zone.get(r["cbp_port_number"])
        if not zone or r["source_updated_raw"] is None:
            continue  # closed, pending and n/a lanes keep having no update time
        # CBP stamps the hour, usually the coming one (a fetch at :26 is stamped with the next hour)
        local = (fetched + timedelta(minutes=40)).astimezone(ZoneInfo(zone)).replace(minute=0, second=0)
        clock = "Noon" if local.hour == 12 else local.strftime("%I:%M %p").lstrip("0").lower()
        r["source_updated_raw"] = f"{local.month}/{local.day}/{local.year} At {clock} {local.tzname()}"
        r["source_tz_abbrev"] = local.tzname()
        if r["delay_min"] is not None:
            d = _wait(r["cbp_port_number"] + r["lane"] + r["lane_type"], local)
            r["delay_min"], r["status_raw"] = d, "no delay" if d == 0 else "delay"
    return stamp, out


def build(datastore, days=30, end=END, keep_percent=35):
    """Writes the runs and returns their fetch times. The newest run is always kept."""
    end_t = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(timezone.utc)
    cbsa_body = (ROOT / "fixtures" / "cbsa-bwt-eng.csv").read_bytes()
    cbp_body = (ROOT / "fixtures" / "cbp-bwt.xml").read_bytes()
    zones = _zones()
    hist = Path(datastore) / "history" / "cbsa_land"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / "2025-12-18T22:31:02.377918.csv").write_bytes((ROOT / "fixtures" / "cbsa-history.csv").read_bytes())
    runs = []
    for hours_back in range(days * 24, -1, -1):
        fetched = end_t - timedelta(hours=hours_back)
        if hours_back and _h("run", fetched.isoformat()) % 100 >= keep_percent:
            continue
        stamp, rows = run_rows(fetched, cbsa_body, cbp_body, zones)
        failures = run_checks(rows["cbsa"] + rows["cbp"])
        assert not failures, failures[:3]
        runs.append((stamp, rows))
    _write(runs, cbsa_body, datastore)
    return [stamp for stamp, _ in runs]


def _write(runs, cbsa_body, datastore):
    """The same files ingest.write.write_run makes (same columns, types and paths), written in one
    DuckDB session: several hundred runs through write_run take minutes, this takes seconds."""
    con = duckdb.connect()
    con.execute("set TimeZone = 'UTC'")
    con.execute("create table r (" + ", ".join(f'"{n}" {t}' for n, t in COLUMNS) + ")")
    with tempfile.TemporaryDirectory() as tmp:
        rows_csv = Path(tmp) / "rows.csv"
        with open(rows_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for _, rows in runs:
                for row in rows["cbsa"] + rows["cbp"]:
                    w.writerow(["\\N" if row[n] is None else str(row[n]).lower() if isinstance(row[n], bool) else row[n] for n in NAMES])
        con.execute(f"copy r from '{rows_csv}' (header false, nullstr '\\N')")
    raw_gz = gzip.compress(cbsa_body, mtime=0)
    for stamp, _ in runs:
        for source in ("cbsa", "cbp"):
            pq, raw = run_paths(datastore, source, stamp)
            pq.parent.mkdir(parents=True, exist_ok=True)
            con.execute(f"""copy (select * from r where source = '{source}' and fetched_at = timestamptz '{stamp}')
                            to '{pq}' (format parquet, compression zstd)""")
            if source == "cbsa":
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(raw_gz)
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m tests.fixture_store")
    ap.add_argument("--datastore", default="datastore")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--end", default=END)
    runs = build(**vars(ap.parse_args()))
    print(f"{len(runs)} runs, {runs[0]} to {runs[-1]}; the last run_id is fx-{runs[-1][:13].replace('-', '').replace('T', '')}")
