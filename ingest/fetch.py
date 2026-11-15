"""Downloads a source and keeps its body and response headers."""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "border-waits-pipeline (+https://github.com/brettadams0/border-waits-pipeline)"
SOURCES = {
    "cbsa": ("https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv", "cbsa-bwt-eng.csv"),
    "cbp": ("https://bwt.cbp.gov/xml/bwt.xml", "cbp-bwt.xml"),
}
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
# A transient failure is retried; anything else (a 404, a 403) is the feed telling us something and fails at once.
RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 3
BACKOFF = (5, 20)   # seconds before the 2nd and 3rd attempt
MAX_WAIT = 60       # the longest a Retry-After header is honoured


def _retry_after(headers):
    try:
        return max(0, int((headers or {}).get("Retry-After", "")))
    except (TypeError, ValueError):
        return None  # absent, or an HTTP date: use the backoff


def fetch(url, timeout=60, opener=urllib.request.urlopen, sleep=time.sleep):
    """Returns (body, headers). At most ATTEMPTS requests, so a run fails within about five minutes per source."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(ATTEMPTS):
        try:
            with opener(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers.items())
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == ATTEMPTS - 1:
                raise
            wait = _retry_after(e.headers)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == ATTEMPTS - 1:
                raise
            wait = None
        sleep(min(BACKOFF[attempt] if wait is None else wait, MAX_WAIT))


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
