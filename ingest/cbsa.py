"""CBSA current waits (Canada-bound), from bwt-eng.csv.

The file is UTF-8 with a BOM, uses ';;' as the delimiter and ends each line
with a trailing ';;'. DuckDB's CSV sniffer rejects that, so it is parsed here.
"""
import re

from . import SCHEMA_VERSION

HEADER = [
    "Customs Office",
    "Location",
    "Last updated",
    "Commercial Flow - Canada bound",
    "Commercial Flow - U.S. bound",
    "Travellers Flow - Canada bound",
    "Travellers Flow - U.S. bound",
]
UPDATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} ([A-Z]{3})$")
MINUTES_RE = re.compile(r"^(\d+) minutes?$")


class ContractError(ValueError):
    """The source no longer matches the format the parser was written for."""


def split_line(line):
    cells = [c.strip() for c in line.split(";;")]
    if cells and cells[-1] == "":
        cells.pop()
    return cells


def parse_status(raw):
    """Returns (delay_min, is_open) for a CBSA status cell."""
    if raw == "No Delay":
        return 0, True
    m = MINUTES_RE.match(raw)
    if m:
        return int(m.group(1)), True
    if raw == "Closed":
        return None, False
    return None, None  # 'Not Applicable' and anything unknown: no reading, openness unknown


def parse(body, run_id, fetched_at):
    text = body.decode("utf-8-sig") if isinstance(body, bytes) else body
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        raise ContractError("cbsa: empty file")
    header = split_line(lines[0])
    if header != HEADER:
        raise ContractError(f"cbsa: header {header!r} != {HEADER!r}")
    rows = []
    for line in lines[1:]:
        cells = split_line(line)
        if len(cells) != len(HEADER):
            raise ContractError(f"cbsa: {len(cells)} cells in {line!r}")
        office, location, updated = cells[0], cells[1], cells[2]
        m = UPDATED_RE.match(updated)
        for lane, raw in (("commercial", cells[3]), ("travellers", cells[5])):
            delay, is_open = parse_status(raw)
            rows.append({
                "run_id": run_id,
                "schema_version": SCHEMA_VERSION,
                "fetched_at": fetched_at,
                "source": "cbsa",
                "source_crossing_name": office,
                "source_location": location,
                "cbp_port_number": None,
                "port_status": None,
                "direction": "to_canada",
                "lane": lane,
                "lane_type": "standard",
                "status_raw": raw,
                "delay_min": delay,
                "is_open": is_open,
                "lanes_open": None,
                "source_updated_raw": updated,
                "source_tz_abbrev": m.group(1) if m else None,
            })
    return rows
