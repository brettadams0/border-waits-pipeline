"""The normalized reading: one row per crossing x direction x lane group per run.

COLUMNS is what the Parquet snapshots store; problems() is the same contract checked at run time on
the parsers' row dictionaries, before anything is written. A column a source cannot supply is None
there (CBP has no update time for a closed lane), never a made-up value.
"""

COLUMNS = [
    ("run_id", "VARCHAR"),
    ("schema_version", "INTEGER"),
    ("fetched_at", "TIMESTAMPTZ"),
    ("source", "VARCHAR"),
    ("source_crossing_name", "VARCHAR"),
    ("source_location", "VARCHAR"),
    ("cbp_port_number", "VARCHAR"),
    ("port_status", "VARCHAR"),
    ("direction", "VARCHAR"),
    ("lane", "VARCHAR"),
    ("lane_type", "VARCHAR"),
    ("status_raw", "VARCHAR"),
    ("delay_min", "INTEGER"),
    ("is_open", "BOOLEAN"),
    ("lanes_open", "INTEGER"),
    ("source_updated_raw", "VARCHAR"),
    ("source_tz_abbrev", "VARCHAR"),
]
NAMES = [name for name, _ in COLUMNS]
PYTHON_TYPES = {"VARCHAR": str, "TIMESTAMPTZ": str, "INTEGER": int, "BOOLEAN": bool}
REQUIRED = ("run_id", "schema_version", "fetched_at", "source", "direction", "lane", "lane_type", "status_raw")
ALLOWED = {
    "source": {"cbsa", "cbp"},
    "direction": {"to_canada", "to_us"},
    "lane": {"travellers", "commercial"},
    "lane_type": {"standard", "nexus_sentri", "fast", "ready"},
}
# The identifier dim_crossing matches each source's rows on.
IDENTIFIER = {"cbsa": "source_crossing_name", "cbp": "cbp_port_number"}


def problems(row):
    """Why a parsed row breaks the contract; empty when it doesn't."""
    out = []
    if list(row) != NAMES:
        return [f"columns {sorted(set(row) ^ set(NAMES))} differ from the schema"]
    for name, sql_type in COLUMNS:
        v = row[name]
        if v is None or v == "":
            if name in REQUIRED:
                out.append(f"{name} is missing")
            continue
        t = PYTHON_TYPES[sql_type]
        if not isinstance(v, t) or (t is int and isinstance(v, bool)):
            out.append(f"{name} {v!r} is not {t.__name__}")
        elif name in ALLOWED and v not in ALLOWED[name]:
            out.append(f"{name} {v!r} is not one of {sorted(ALLOWED[name])}")
    ident = IDENTIFIER.get(row["source"])
    if ident and not row[ident]:
        out.append(f"{ident} is missing")
    return out
