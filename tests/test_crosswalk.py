"""Every name in the crosswalk must exist in the fixtures it was built from."""
import csv
from pathlib import Path

from ingest import cbp, cbsa

ROOT = Path(__file__).resolve().parent.parent
SEED = list(csv.DictReader(open(ROOT / "dbt" / "seeds" / "dim_crossing.csv", encoding="utf-8")))


def test_names_exist_in_fixtures():
    live = {r["source_crossing_name"] for r in cbsa.parse((ROOT / "fixtures" / "cbsa-bwt-eng.csv").read_bytes(), "1", "t")}
    ports = {(r["cbp_port_number"], r["source_crossing_name"]) for r in cbp.parse((ROOT / "fixtures" / "cbp-bwt.xml").read_bytes(), "1", "t")}
    hist = {r["Port of Entry"].strip() for r in csv.DictReader(open(ROOT / "fixtures" / "cbsa-history.csv", encoding="utf-8-sig"))}
    for row in SEED:
        assert not row["cbsa_csv_name"] or row["cbsa_csv_name"] in live, row
        assert not row["cbsa_history_name"] or row["cbsa_history_name"] in hist, row
        if row["cbp_port_number"]:
            assert (row["cbp_port_number"], row["cbp_crossing_name"]) in ports, row
    # every live crossing is in the crosswalk once
    assert sorted(r["cbsa_csv_name"] for r in SEED if r["cbsa_csv_name"]) == sorted(live)
    assert sorted(r["cbp_port_number"] for r in SEED if r["cbp_port_number"]) == sorted({p for p, _ in ports})


def test_ids_and_featured():
    ids = [r["crossing_id"] for r in SEED]
    assert len(ids) == len(set(ids))
    assert sorted(r["crossing_id"] for r in SEED if r["featured"] == "true") == [
        "ambassador_bridge", "detroit_windsor_tunnel", "gordie_howe_bridge"]
