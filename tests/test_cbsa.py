from pathlib import Path

from ingest import cbsa
from ingest.checks import run_checks

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cbsa-bwt-eng.csv"
HEAD = ";;".join(cbsa.HEADER) + ";;"


def test_status_values():
    assert cbsa.parse_status("No Delay") == (0, True)
    assert cbsa.parse_status("12 minutes") == (12, True)
    assert cbsa.parse_status("1 minute") == (1, True)
    assert cbsa.parse_status("Closed") == (None, False)
    assert cbsa.parse_status("Not Applicable") == (None, None)


def test_bom_delimiter_and_trailing_cell():
    body = ("﻿" + HEAD + "\nAmbassador Bridge;;Windsor, ON;;2026-10-20 23:15 EDT;;No Delay;;--;;5 minutes;;--;;\n").encode()
    rows = cbsa.parse(body, "1-1", "2026-10-21T03:20:00Z")
    assert [(r["lane"], r["delay_min"]) for r in rows] == [("commercial", 0), ("travellers", 5)]
    assert rows[0]["source_crossing_name"] == "Ambassador Bridge"
    assert rows[0]["source_tz_abbrev"] == "EDT"
    assert all(r["direction"] == "to_canada" and r["lane_type"] == "standard" for r in rows)


def test_header_contract():
    body = HEAD.replace("Location", "Place") + "\n"
    try:
        cbsa.parse(body, "1-1", "t")
    except cbsa.ContractError:
        return
    raise AssertionError("a changed header must fail the contract")


def test_fixture():
    if not FIXTURE.exists():
        return  # skipped until the real response is saved
    rows = cbsa.parse(FIXTURE.read_bytes(), "1-1", "t")
    assert len({r["source_crossing_name"] for r in rows}) >= 25
    assert not [f for f in run_checks(rows) if f.startswith("cbsa")]
