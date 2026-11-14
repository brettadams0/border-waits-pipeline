"""Per-run checks. They run after parsing and before anything is written."""
import re
from datetime import datetime

from . import schema

MIN_CROSSINGS = 25
MAX_DELAY = 720
FORMATS = {
    "cbsa": re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) [A-Z]{3}$"),
    # 'At Noon EDT' instead of 'At 12:00 pm EDT' is in fixtures/cbp-bwt.xml (2026-10-27)
    "cbp": re.compile(r"^(\d{1,2}/\d{1,2}/\d{4}) At (\d{1,2}:\d{2} [ap]m|Noon) [A-Z]{3}$"),
}


def update_time_ok(source, raw):
    """The published update time has the source's format AND names a real date and time
    ('2026-02-30 10:00 EST' and '13/45/2026 At 1:00 pm EST' have the format but no such day)."""
    m = FORMATS[source].match(raw)
    if not m:
        return False
    try:
        if source == "cbsa":
            datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        else:
            clock = "12:00 pm" if m.group(2) == "Noon" else m.group(2)
            datetime.strptime(f"{m.group(1)} {clock}", "%m/%d/%Y %I:%M %p")
    except ValueError:
        return False
    return True


def run_checks(rows):
    """Returns a list of failure messages; empty means the run may be written."""
    failures = []
    for source in ("cbsa", "cbp"):
        names = {r["source_crossing_name"] if source == "cbsa" else r["cbp_port_number"]
                 for r in rows if r["source"] == source}
        if len(names) < MIN_CROSSINGS:
            failures.append(f"{source}: {len(names)} crossings, need at least {MIN_CROSSINGS}")
    for r in rows:
        where = f"{r.get('source')} {r.get('source_crossing_name') or r.get('cbp_port_number')}"
        broken = schema.problems(r)
        if broken:
            failures.extend(f"{where}: {b}" for b in broken)
            continue
        d = r["delay_min"]
        if d is not None and not 0 <= d <= MAX_DELAY:
            failures.append(f"{where}: delay_min {d} outside 0-{MAX_DELAY}")
        raw = r["source_updated_raw"]
        if raw is not None and not update_time_ok(r["source"], raw):
            failures.append(f"{where}: source_updated_raw {raw!r} doesn't parse")
    return failures
