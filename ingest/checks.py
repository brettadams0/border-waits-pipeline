"""Per-run checks. They run after parsing and before anything is written."""
import re

MIN_CROSSINGS = 25
MAX_DELAY = 720
FORMATS = {
    "cbsa": re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Z]{3}$"),
    # 'At Noon EDT' instead of 'At 12:00 pm EDT' is in fixtures/cbp-bwt.xml (2026-10-27);
    # 'At Midnight MDT' in fixtures/cbp-bwt-midnight.xml failed run 40829314499 (2026-10-29)
    "cbp": re.compile(r"^\d{1,2}/\d{1,2}/\d{4} At (\d{1,2}:\d{2} [ap]m|Noon|Midnight) [A-Z]{3}$"),
}


def run_checks(rows):
    """Returns a list of failure messages; empty means the run may be written."""
    failures = []
    for source in ("cbsa", "cbp"):
        names = {r["source_crossing_name"] if source == "cbsa" else r["cbp_port_number"]
                 for r in rows if r["source"] == source}
        if len(names) < MIN_CROSSINGS:
            failures.append(f"{source}: {len(names)} crossings, need at least {MIN_CROSSINGS}")
    for r in rows:
        d = r["delay_min"]
        if d is not None and not 0 <= d <= MAX_DELAY:
            failures.append(f"{r['source']} {r['source_crossing_name']}: delay_min {d} outside 0-{MAX_DELAY}")
        raw = r["source_updated_raw"]
        if raw is not None and not FORMATS[r["source"]].match(raw):
            failures.append(f"{r['source']} {r['source_crossing_name']}: source_updated_raw {raw!r} doesn't parse")
    return failures
