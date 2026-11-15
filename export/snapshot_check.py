"""Checks the page's saved snapshot (web/fallback/): python -m export.snapshot_check [web/fallback] [--max-age-days N]

Run it when the snapshot is refreshed for a release. Without --max-age-days it checks only what stays
true forever (the test suite runs it that way, so old commits keep passing): every file matches its
hash, the pair meets the page's contract, the rebuild check holds over the bundle's own file, only the
featured crossings are in it, and the chart has something to draw. --max-age-days adds the one check
that depends on today: the newest reading must be that recent.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import contract


def check(directory, max_age_days=None, now=None):
    """Returns (problems, facts)."""
    import duckdb
    from .__main__ import CHART, rebuild_check
    d = Path(directory)
    problems = []
    try:
        m = json.loads((d / "manifest.json").read_text())
        s = json.loads((d / m["files"]["summary"]["url"]).read_text())
    except (OSError, ValueError, KeyError) as e:
        return [f"cannot read the snapshot: {e}"], {}
    problems += contract.problems(m, s)
    for name, f in m["files"].items():
        path = d / f["url"]
        if not path.is_file():
            problems.append(f"{name}: {f['url']} is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
            problems.append(f"{name}: {f['url']} does not match its sha256")
    listed = {f["url"] for f in m["files"].values()} | {"manifest.json", "status.json"}
    strays = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and p.relative_to(d).as_posix() not in listed)
    if strays:
        problems.append(f"files the manifest does not name (left over from an earlier snapshot?): {strays}")
    if not problems:
        rc = m["rebuild_check"]
        if rebuild_check((d / rc["sql"]).read_text(), d / rc["input"]) != rc["expected"]:
            problems.append("the rebuild check does not match over the bundle's own file")
        ids = {c["crossing_id"] for c in s["crossings"]}
        stored = {r[0] for r in duckdb.sql(f"select distinct crossing_id from read_parquet('{d / m['files']['fct_wait_readings']['url']}')").fetchall()}
        if stored != ids or m.get("sample", {}).get("scope") != "featured":
            problems.append(f"expected only the featured crossings {sorted(ids)}, found {sorted(stored)}")
    gates = {**CHART, **(s.get("chart") or {})}
    drawable = sum(1 for r in s["by_hour"] if r.get("median_delay_min") is not None and (r.get("valid_days") or 0) >= gates["min_days_point"])
    if not drawable:
        problems.append("no hour has enough days to draw: the chart would open empty")
    seen = [r["observed_at"] for r in s["latest"] if r.get("observed_at")]
    newest = datetime.fromisoformat(max(seen) + ":00") if seen else None
    age = None if newest is None else ((now or datetime.now(timezone.utc)) - newest).total_seconds() / 86400
    if len(s["latest"]) < len(s["crossings"]) * 2:
        problems.append(f"only {len(s['latest'])} latest readings for {len(s['crossings'])} crossings")
    if max_age_days is not None and (age is None or age > max_age_days):
        problems.append(f"the newest reading is {age:.1f} days old, more than {max_age_days}: refresh the snapshot" if age is not None else "no dated reading")
    return problems, {"readings_through": None if newest is None else newest.isoformat(), "age_days": None if age is None else round(age, 1),
                      "drawable_hours": drawable, "bytes": sum(p.stat().st_size for p in d.rglob("*") if p.is_file()), "data_sha": m.get("data_sha")}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m export.snapshot_check")
    ap.add_argument("directory", nargs="?", default="web/fallback")
    ap.add_argument("--max-age-days", type=float)
    a = ap.parse_args(argv)
    problems, facts = check(a.directory, a.max_age_days)
    print(json.dumps(facts))
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
