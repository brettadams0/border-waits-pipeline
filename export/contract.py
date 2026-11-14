"""The contract between the export and the page: what web/app.js `valid()` accepts.

The export validates what it is about to publish with the same rules the page applies to what it
loads, so a payload the page would refuse never replaces a good one. Additive fields don't change
SCHEMA_VERSION; removing or re-meaning a field the page reads does, and the page then shows its
saved snapshot until it is updated.
"""
import re
from datetime import datetime

SCHEMA_VERSION = 1
DIRECTIONS = ("to_canada", "to_us")
LANES = ("travellers", "commercial")
URL_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*$")  # relative, inside the data directory
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")  # a table name the console may use as an identifier
REQUIRED_FILES = ("summary", "dim_crossing", "fct_wait_readings", "fct_wait_readings_recent")


def _number(v, allow_none=False):
    return (v is None and allow_none) or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v >= 0)


def _time(v, allow_none=False):
    if v is None:
        return allow_none
    try:
        # DuckDB writes '2026-10-27 17:00:00+00'; the manifest writes '2026-10-27T17:00:00Z'
        datetime.fromisoformat(re.sub(r"([+-]\d\d)$", r"\1:00", str(v).replace("Z", "+00:00")))
        return True
    except ValueError:
        return False


def problems(manifest, summary):
    """Every way the pair breaks the contract; empty when it is valid."""
    out = []
    if not isinstance(manifest, dict) or not isinstance(summary, dict):
        return ["manifest and summary must be objects"]
    if manifest.get("schema_version") != SCHEMA_VERSION:
        out.append(f"schema_version {manifest.get('schema_version')!r}, expected {SCHEMA_VERSION}")
    if not _time(manifest.get("generated_at")):
        out.append("generated_at is not a time")
    files = manifest.get("files")
    if not isinstance(files, dict):
        out.append("files is not an object")
        files = {}
    for name in REQUIRED_FILES:
        if name not in files:
            out.append(f"files.{name} is missing")
    for name, f in files.items():
        url = f.get("url") if isinstance(f, dict) else None
        if not isinstance(url, str) or not URL_RE.match(url) or ".." in url:
            out.append(f"files.{name}.url {url!r} is not a relative path inside the data directory")
        elif url.endswith(".parquet") and not NAME_RE.match(name):
            out.append(f"files.{name}: not a usable table name")
    if not isinstance(manifest.get("sources"), dict):
        out.append("sources is not an object")
    for key in ("crossings", "latest", "by_hour"):
        if not isinstance(summary.get(key), list):
            out.append(f"summary.{key} is not a list")
    for c in summary.get("crossings") or []:
        if not isinstance(c, dict) or not isinstance(c.get("crossing_id"), str) or not isinstance(c.get("display_name"), str):
            out.append(f"summary.crossings: bad row {c!r}")
    for r in summary.get("latest") or []:
        ok = (isinstance(r, dict) and isinstance(r.get("crossing_id"), str) and r.get("direction") in DIRECTIONS
              and r.get("lane") in LANES and _number(r.get("delay_min"), True)
              and r.get("is_open") in (True, False, None) and _time(r.get("source_updated_at"), True)
              and _time(r.get("observed_at"), True))
        if not ok:
            out.append(f"summary.latest: bad row {r!r}")
    for r in summary.get("by_hour") or []:
        ok = (isinstance(r, dict) and isinstance(r.get("crossing_id"), str) and r.get("direction") in DIRECTIONS
              and r.get("lane") in LANES and isinstance(r.get("local_hour"), int) and 0 <= r["local_hour"] <= 23
              and _number(r.get("n")) and _number(r.get("days")) and _number(r.get("valid_days"), True)
              and _number(r.get("median_delay_min"), True) and _number(r.get("p90_delay_min"), True))
        if not ok:
            out.append(f"summary.by_hour: bad row {r!r}")
    return out


def validate(manifest, summary):
    found = problems(manifest, summary)
    if found:
        raise ValueError("export contract: " + "; ".join(found[:5]))
