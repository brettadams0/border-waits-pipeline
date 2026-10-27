"""CBSA's monthly service-standard history, checked once a day.

The CKAN package's metadata_modified is compared with the newest stored file;
the CSV (behind a redirect to a signed blob) is downloaded only when it changed,
to history/cbsa_land/<metadata_modified>.csv.
"""
import json
from pathlib import Path

from . import fetch

PACKAGE_URL = "https://open.canada.ca/data/api/action/package_show?id=000fe5aa-1d77-42d1-bfe7-458c51dacfef"
RESOURCE_PREFIX = "Historical Border Wait Times - "  # the English resource; the French one says "Time"


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


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m ingest.history")
    ap.add_argument("--datastore", default="datastore")
    written = update(ap.parse_args().datastore)
    print(written or "history: stored file is current")
