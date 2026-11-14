"""D05/F07: semantic checks on the parsed rows, bounded retries, and the history check's timing."""
import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest import cbp, cbsa, checks, fetch, history, schema

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def good_rows():
    return (cbsa.parse((FIX / "cbsa-bwt-eng.csv").read_bytes(), "1-1", "2026-10-27T17:26:00Z")
            + cbp.parse((FIX / "cbp-bwt.xml").read_bytes(), "1-1", "2026-10-27T17:26:00Z"))


def test_fixture_rows_meet_the_row_contract():
    assert [p for r in good_rows() for p in schema.problems(r)] == []


@pytest.mark.parametrize("source, raw, ok", [
    ("cbsa", "2026-10-27 13:05 EDT", True),
    ("cbsa", "2026-02-30 10:00 EST", False),      # the format, but no such day
    ("cbsa", "2026-10-27 24:10 EDT", False),
    ("cbsa", "2026-13-01 10:00 EDT", False),
    ("cbp", "10/27/2026 At 1:00 pm EDT", True),
    ("cbp", "10/27/2026 At Noon EDT", True),
    ("cbp", "13/45/2026 At 1:00 pm EDT", False),
    ("cbp", "2/30/2026 At 1:00 pm EST", False),
    ("cbp", "10/27/2026 At 13:00 pm EDT", False),
    ("cbp", "10/27/2026 1:00 pm EDT", False),
])
def test_update_times_must_be_real_dates(source, raw, ok):
    assert checks.update_time_ok(source, raw) is ok
    rows = good_rows()
    row = next(r for r in rows if r["source"] == source and r["source_updated_raw"])
    row["source_updated_raw"] = raw
    assert (not [f for f in checks.run_checks(rows) if "doesn't parse" in f]) is ok


@pytest.mark.parametrize("change, expect", [
    (lambda r: r.update(direction="north"), "direction 'north' is not one of"),
    (lambda r: r.update(lane="bus"), "lane 'bus' is not one of"),
    (lambda r: r.update(delay_min="12"), "delay_min '12' is not int"),
    (lambda r: r.update(delay_min=True), "delay_min True is not int"),
    (lambda r: r.update(is_open="yes"), "is_open 'yes' is not bool"),
    (lambda r: r.update(run_id=""), "run_id is missing"),
    (lambda r: r.update(status_raw=None), "status_raw is missing"),
    (lambda r: r.pop("lanes_open"), "differ from the schema"),
    (lambda r: r.update(extra=1), "differ from the schema"),
])
def test_a_row_outside_the_contract_stops_the_run(change, expect):
    rows = good_rows()
    change(rows[0])
    failures = checks.run_checks(rows)
    assert any(expect in f for f in failures), failures[:3]


def test_missing_identifiers_are_contract_failures():
    rows = good_rows()
    next(r for r in rows if r["source"] == "cbp")["cbp_port_number"] = ""
    assert any("cbp_port_number is missing" in f for f in checks.run_checks(rows))
    body = (FIX / "cbp-bwt.xml").read_text().replace("<port_number>380001</port_number>", "<port_number></port_number>")
    with pytest.raises(cbsa.ContractError, match="no port_number"):
        cbp.parse(body.encode(), "1-1", "t")
    head = ";;".join(cbsa.HEADER) + ";;"
    with pytest.raises(cbsa.ContractError, match="no customs office"):
        cbsa.parse(head + "\n;;Windsor, ON;;2026-10-20 23:15 EDT;;No Delay;;--;;5 minutes;;--;;\n", "1-1", "t")


def test_empty_feeds_write_nothing():
    head = ";;".join(cbsa.HEADER) + ";;"
    with pytest.raises(cbsa.ContractError, match="empty file"):
        cbsa.parse(b"", "1-1", "t")
    failures = checks.run_checks(cbsa.parse(head + "\n", "1-1", "t"))      # a header and no crossings
    assert "cbsa: 0 crossings, need at least 25" in failures and "cbp: 0 crossings, need at least 25" in failures
    no_ports = b"<border_wait_time><last_updated_date>d</last_updated_date><last_updated_time>t</last_updated_time><number_of_ports>0</number_of_ports></border_wait_time>"
    assert cbp.parse(no_ports, "1-1", "t") == []


def test_statuses_closed_unknown_and_unseen():
    assert cbsa.parse_status("Temporarily closed") == (None, False)       # seen live 2026-10-28
    assert cbsa.parse_status("Bridge on fire") == (None, None)            # unseen: no number, openness unknown; dbt warns
    assert cbp.parse_status("Something New", "30") == (None, None)        # never a number from an unknown status


# ---- F07: bounded retries ----

class Resp:
    def __init__(self, body=b"ok"):
        self.body, self.headers = body, {"Content-Type": "text/plain"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def flaky(*outcomes):
    calls, waits = [], []
    it = iter(outcomes)

    def opener(req, timeout):
        calls.append(req.full_url)
        o = next(it)
        if isinstance(o, Exception):
            raise o
        return o
    return opener, calls, waits


def http_error(code, retry_after=None):
    return urllib.error.HTTPError("https://example.test/x", code, "nope", {"Retry-After": retry_after} if retry_after else {}, io.BytesIO(b""))


def test_transient_failures_are_retried_then_succeed():
    opener, calls, waits = flaky(http_error(503), TimeoutError("slow"), Resp(b"feed"))
    body, headers = fetch.fetch("https://example.test/x", opener=opener, sleep=waits.append)
    assert body == b"feed" and len(calls) == 3 and waits == list(fetch.BACKOFF)


def test_retry_after_is_respected_up_to_a_cap():
    opener, calls, waits = flaky(http_error(429, "7"), http_error(429, "86400"), Resp())
    fetch.fetch("https://example.test/x", opener=opener, sleep=waits.append)
    assert waits == [7, fetch.MAX_WAIT]


def test_retries_are_bounded_and_the_last_error_surfaces():
    opener, calls, waits = flaky(*[urllib.error.URLError("down")] * 5)
    with pytest.raises(urllib.error.URLError):
        fetch.fetch("https://example.test/x", opener=opener, sleep=waits.append)
    assert len(calls) == fetch.ATTEMPTS and len(waits) == fetch.ATTEMPTS - 1
    assert sum(waits) + fetch.ATTEMPTS * 60 <= 300          # the whole thing fails inside five minutes


def test_a_definite_answer_is_not_retried():
    opener, calls, waits = flaky(http_error(404), Resp())
    with pytest.raises(urllib.error.HTTPError):
        fetch.fetch("https://example.test/x", opener=opener, sleep=waits.append)
    assert len(calls) == 1 and waits == []


# ---- F07: the history check no longer depends on a run arriving in one particular hour ----

def downloader(counter):
    def download(url):
        counter.append(url)
        if "package_show" in url:
            return (FIX / "ckan-package_show.json").read_bytes(), {}
        return (FIX / "cbsa-history.csv").read_bytes(), {}
    return download


def test_history_is_checked_by_elapsed_time_not_by_the_hour(tmp_path):
    calls = []
    t0 = datetime(2026, 11, 14, 13, 17, tzinfo=timezone.utc)     # not 06:00 UTC, the only hour the old check ran in
    assert history.check(tmp_path, t0, downloader(calls)) == "updated" and len(calls) == 2
    assert history.check(tmp_path, t0 + timedelta(hours=1), downloader(calls)) == "skipped" and len(calls) == 2
    assert history.check(tmp_path, t0 + timedelta(hours=23, minutes=59), downloader(calls)) == "skipped"
    # a day on, at whatever hour the scheduler happens to fire: one request, the stored file is current
    assert history.check(tmp_path, t0 + timedelta(hours=24, minutes=30), downloader(calls)) == "current" and len(calls) == 3
    state = json.loads((tmp_path / "history" / "cbsa_land_check.json").read_text())
    assert state["result"] == "current" and state["checked_at"] == "2026-11-15T13:47:00Z"
    assert [p.name for p in (tmp_path / "history" / "cbsa_land").iterdir()] == ["2025-12-18T22:31:02.377918.csv"]   # the state file stays out of dbt's glob


def test_a_failed_history_check_keeps_the_run_and_retries_after_an_hour(tmp_path):
    calls = []
    t0 = datetime(2026, 11, 14, 13, 17, tzinfo=timezone.utc)
    history.check(tmp_path, t0, downloader(calls))

    def broken(url):
        calls.append(url)
        raise urllib.error.URLError("CKAN is down")
    t1 = t0 + timedelta(hours=25)
    assert history.check(tmp_path, t1, broken) == "failed"                      # reported, not raised
    assert history.check(tmp_path, t1 + timedelta(minutes=30), broken) == "skipped"   # not hammered on every run
    assert history.check(tmp_path, t1 + timedelta(minutes=61), downloader(calls)) == "current"
    assert json.loads((tmp_path / "history" / "cbsa_land_check.json").read_text())["error"] is None
