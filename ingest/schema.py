"""The normalized reading: one row per crossing x direction x lane group per run."""

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
