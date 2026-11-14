"""CBSA's monthly service-standard history, checked about once a day.

The CKAN package's metadata_modified is compared with the newest stored file;
the CSV (behind a redirect to a signed blob) is downloaded only when it changed,
to history/cbsa_land/<metadata_modified>.csv.

When to check is decided by the time since the last check, kept in
history/cbsa_land_check.json on the data branch, not by the hour of the run:
GitHub drops scheduled runs, and a check tied to one hour of the day was skipped
whenever that hour's run didn't fire. A failed check is retried after an hour and
never fails the run: the feeds were already collected.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import fetch

PACKAGE_URL = "https://open.canada.ca/data/api/action/package_show?id=000fe5aa-1d77-42d1-bfe7-458c51dacfef"
RESOURCE_PREFIX = "Historical Border Wait Times - "  # the English resource; the French one says "Time"
CHECK_EVERY = timedelta(hours=24)
RETRY_AFTER = timedelta(hours=1)


def resource_url(package):
    matches = [r["url"] for r in package["resources"]
               if r.get("format") == "CSV" and r["name"].startswith(RESOURCE_PREFIX)]
    if len(matches) != 1:
        raise ValueError(f"expected one '{RESOURCE_PREFIX}…' CSV resource, found {len(matches)}")
    return matches[0]


def update(datastore, package_body=None, download=fetch.fetch):
    """Returns the path written, or None when the stored file is current."""
    if package_body is None:
        package_body, _ = download(PACKAGE_URL)
    package = json.loads(package_body)["result"]
    modified = package["metadata_modified"]
    target = Path(datastore) / "history" / "cbsa_land" / f"{modified}.csv"
    if target.exists():
        return None
    body, _ = download(resource_url(package))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


def _state_path(datastore):
    return Path(datastore) / "history" / "cbsa_land_check.json"


def _read_state(datastore):
    try:
        return json.loads(_state_path(datastore).read_text())
    except (OSError, ValueError):
        return {}


def _parse(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def due(datastore, now):
    """True when no file is stored yet, or the last good check is a day old and the last attempt an hour old."""
    if not any((Path(datastore) / "history" / "cbsa_land").glob("*.csv")):
        return True
    state = _read_state(datastore)
    attempted, checked = _parse(state.get("attempted_at")), _parse(state.get("checked_at"))
    if attempted and now - attempted < RETRY_AFTER:
        return False
    return checked is None or now - checked >= CHECK_EVERY


def check(datastore, now=None, download=fetch.fetch):
    """Runs the check when it is due. Returns 'skipped', 'current', 'updated' or 'failed'; never raises."""
    now = now or datetime.now(timezone.utc)
    if not due(datastore, now):
        return "skipped"
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {**_read_state(datastore), "attempted_at": stamp}
    path = _state_path(datastore)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        written = update(datastore, download=download)
        state.update(checked_at=stamp, result="updated" if written else "current", error=None)
    except Exception as e:  # the network, CKAN's JSON, a renamed resource: report it, keep the run
        state.update(result="failed", error=f"{type(e).__name__}: {e}"[:300])
        print(f"history: check failed, will retry in an hour: {state['error']}", file=sys.stderr)
    path.write_text(json.dumps(state, indent=1) + "\n")
    return state["result"]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m ingest.history")
    ap.add_argument("--datastore", default="datastore")
    print(f"history: {check(ap.parse_args().datastore)}")
