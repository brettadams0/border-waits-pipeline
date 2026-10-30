from pathlib import Path

from ingest import cbp, cbsa
from ingest.checks import run_checks

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def rows():
    return cbp.parse((FIX / "cbp-bwt.xml").read_bytes(), "1-1", "2026-10-27T17:26:00Z")


def test_fixture_canadian_ports_and_lane_groups():
    r = rows()
    assert len({x["cbp_port_number"] for x in r}) == 30
    assert {(x["lane"], x["lane_type"]) for x in r} == {
        ("commercial", "standard"), ("commercial", "fast"),
        ("travellers", "standard"), ("travellers", "nexus_sentri"), ("travellers", "ready")}
    assert all(x["direction"] == "to_us" for x in r)


def test_ambassador_bridge_row():
    amb = [x for x in rows() if x["cbp_port_number"] == "380001" and x["lane"] == "travellers" and x["lane_type"] == "standard"][0]
    assert amb["source_crossing_name"] == "Ambassador Bridge" and amb["source_location"] == "Detroit"
    assert amb["status_raw"] == "delay" and amb["delay_min"] == 10 and amb["is_open"] and amb["lanes_open"] == 3
    assert amb["source_updated_raw"] == "10/27/2026 At 1:00 pm EDT" and amb["source_tz_abbrev"] == "EDT"


def test_names_are_stripped():
    assert all(x["source_crossing_name"] == x["source_crossing_name"].strip() for x in rows())


def test_status_mapping():
    assert cbp.parse_status("delay", "15") == (15, True)
    assert cbp.parse_status("no delay", "5") == (0, True)  # seen in the feed: status wins
    assert cbp.parse_status("Lanes Closed", "") == (None, False)
    assert cbp.parse_status("N/A", "") == (None, None)
    assert cbp.parse_status("Update Pending", "") == (None, None)


def test_closed_lane_has_no_update_time():
    closed = [x for x in rows() if x["status_raw"] == "Lanes Closed"]
    assert closed and all(x["source_updated_raw"] is None for x in closed)


def test_checks_pass_on_both_fixtures():
    all_rows = rows() + cbsa.parse((FIX / "cbsa-bwt-eng.csv").read_bytes(), "1-1", "t")
    assert run_checks(all_rows) == []


def test_contract_failures():
    for body in (b"<nope/>", b"not xml",
                 b"<border_wait_time><last_updated_date>d</last_updated_date><last_updated_time>t</last_updated_time>"
                 b"<number_of_ports>2</number_of_ports><port/></border_wait_time>"):
        try:
            cbp.parse(body, "1-1", "t")
        except cbsa.ContractError:
            continue
        raise AssertionError(body)


def test_noon_is_published_as_a_word():
    noon = [x for x in rows() if x["source_updated_raw"] and "Noon" in x["source_updated_raw"]]
    assert noon and all(x["source_updated_raw"].endswith(("Noon EDT", "Noon CDT", "Noon EST")) for x in noon)
    assert not [f for f in run_checks(noon) if "doesn't parse" in f]


def test_midnight_is_published_as_a_word():
    # Run 40829314499 failed its per-run checks on these two rows.
    r = cbp.parse((FIX / "cbp-bwt-midnight.xml").read_bytes(), "1-1", "2026-10-29T06:28:00Z")
    midnight = [x for x in r if x["source_updated_raw"] and "Midnight" in x["source_updated_raw"]]
    assert [x["source_updated_raw"] for x in midnight] == ["10/29/2026 At Midnight MDT"] * 2
    assert not [f for f in run_checks(r) if "doesn't parse" in f]
