"""CBP current waits (US-bound), from bwt.xml.

Only `border == "Canadian Border"` ports are kept. Every lane group under the
commercial and passenger lanes becomes a row; the element names below are the
ones in fixtures/cbp-bwt.xml, and an unknown one is a contract failure.
"""
import xml.etree.ElementTree as ET

from . import SCHEMA_VERSION
from .cbsa import ContractError

LANES = {"commercial_vehicle_lanes": "commercial", "passenger_vehicle_lanes": "travellers"}
LANE_TYPES = {
    "standard_lanes": "standard",
    "FAST_lanes": "fast",
    "NEXUS_SENTRI_lanes": "nexus_sentri",
    "ready_lanes": "ready",
}
ROOT_FIELDS = ("last_updated_date", "last_updated_time", "number_of_ports")


def text(el, tag):
    return (el.findtext(tag) or "").strip()


def to_int(s):
    return int(s) if s.isdigit() else None


def parse_status(status, delay_minutes):
    """Returns (delay_min, is_open). `no delay` is 0 even when delay_minutes says
    otherwise (seen in the feed); status_raw keeps what was published."""
    if status == "delay":
        return to_int(delay_minutes), True
    if status == "no delay":
        return 0, True
    if status == "Lanes Closed":
        return None, False
    return None, None  # 'N/A', 'Update Pending' and anything unknown


def parse(body, run_id, fetched_at):
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise ContractError(f"cbp: XML does not parse: {e}") from e
    if root.tag != "border_wait_time":
        raise ContractError(f"cbp: root is <{root.tag}>")
    for field in ROOT_FIELDS:
        if not text(root, field):
            raise ContractError(f"cbp: root field {field} missing")
    if to_int(text(root, "number_of_ports")) != len(root.findall("port")):
        raise ContractError("cbp: number_of_ports doesn't match the <port> count")
    rows = []
    for port in root.findall("port"):
        if text(port, "border") != "Canadian Border":
            continue
        date = text(port, "date")
        for group_tag, lane in LANES.items():
            group = port.find(group_tag)
            if group is None:
                raise ContractError(f"cbp: {text(port, 'port_number')} has no {group_tag}")
            for el in group:
                if el.tag == "maximum_lanes":
                    continue
                if el.tag not in LANE_TYPES:
                    raise ContractError(f"cbp: unknown lane group {group_tag}/{el.tag}")
                status = text(el, "operational_status")
                update = text(el, "update_time")
                delay, is_open = parse_status(status, text(el, "delay_minutes"))
                rows.append({
                    "run_id": run_id,
                    "schema_version": SCHEMA_VERSION,
                    "fetched_at": fetched_at,
                    "source": "cbp",
                    "source_crossing_name": text(port, "crossing_name"),
                    "source_location": text(port, "port_name"),
                    "cbp_port_number": text(port, "port_number"),
                    "port_status": text(port, "port_status"),
                    "direction": "to_us",
                    "lane": lane,
                    "lane_type": LANE_TYPES[el.tag],
                    "status_raw": status,
                    "delay_min": delay,
                    "is_open": is_open,
                    "lanes_open": to_int(text(el, "lanes_open")),
                    "source_updated_raw": f"{date} {update}" if update else None,
                    "source_tz_abbrev": update.split()[-1] if update else None,
                })
    return rows
