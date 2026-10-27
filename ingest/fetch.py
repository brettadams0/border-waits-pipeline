"""Downloads a source and keeps its body and response headers."""
import json
import urllib.request
from pathlib import Path

USER_AGENT = "border-waits-pipeline (+https://github.com/brettadams0/border-waits-pipeline)"
SOURCES = {
    "cbsa": ("https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv", "cbsa-bwt-eng.csv"),
    "cbp": ("https://bwt.cbp.gov/xml/bwt.xml", "cbp-bwt.xml"),
}
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers.items())


def get(source, raw_dir, fixtures=False):
    """Returns the body; saves body and headers under raw_dir for the workflow artifact."""
    url, name = SOURCES[source]
    if fixtures:
        body, headers = (FIXTURES / name).read_bytes(), {"x-fixture": name}
    else:
        body, headers = fetch(url)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / name).write_bytes(body)
    (raw_dir / f"{name}.headers.json").write_text(json.dumps({"url": url, **headers}, indent=1))
    return body
