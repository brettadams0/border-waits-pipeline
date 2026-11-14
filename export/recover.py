"""Builds the Pages site to publish when a run fails: the last good export, complete, with an honest status.json.

python -m export.recover --published datastore/published --out public --run-id ID --failed-step NAME
                         [--collected true|false] [--run-url URL] [--docs last-good-docs.html]

Pages replaces the whole site on every deploy, so the recovery site has to carry everything the last good
one did: the data directory (kept on the data branch under published/) and the dbt docs (not kept there,
1 MB a run; the workflow fetches the copy that is live and passes it as --docs). When no export has ever
succeeded there is nothing to republish: the site then holds only status.json, saying so, and the page
shows its saved snapshot.

Standard library only: the failure job runs this without installing anything.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Which part of the run each workflow step belongs to (a set-up step such as the checkout is "unknown").
STAGES = {"Ingest": "collect", "Store the run's snapshots": "collect",
          "dbt build": "build",
          "Export and docs": "publish", "Store the published export": "publish", "deploy": "publish"}
NO_DOCS = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>border-waits docs</title></head>
<body><p>The dbt docs are rebuilt by the next successful pipeline run. <a href="../data/v1/status.json">status.json</a> has the state of the last run.</p></body></html>
"""
NO_DATA = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>border-waits data</title></head>
<body><p>No pipeline run has published data yet. <a href="status.json">status.json</a> has the state of the last run.</p></body></html>
"""


def recover(published, out, run_id, failed_step, run_url="", docs=None, now=None, collected=None):
    """collected: whether this run's snapshots reached the data branch before it failed (they are
    committed right after ingest). None infers it from the failed step."""
    published, out = Path(published), Path(out)
    data = out / "data" / "v1"
    last = published / "data" / "v1"
    last_success = None
    if (last / "manifest.json").is_file():
        shutil.copytree(published / "data", out / "data", dirs_exist_ok=True)
        try:
            previous = json.loads((last / "status.json").read_text())
            # after two failures in a row the stored status is itself a failure: keep the success inside it
            last_success = previous if previous.get("result") == "success" else previous.get("last_success")
        except (OSError, ValueError):
            last_success = None
    else:
        data.mkdir(parents=True, exist_ok=True)
        (data / "index.html").write_text(NO_DATA)
    stage = STAGES.get(failed_step, "unknown")
    status = {"run_id": run_id, "time": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "result": "failure", "failed_step": failed_step, "failed_stage": stage,
              "collected": stage in ("build", "publish") if collected is None else bool(collected),
              "run_url": run_url, "last_success": last_success}
    (data / "status.json").write_text(json.dumps(status, indent=1))
    (out / "docs").mkdir(parents=True, exist_ok=True)
    docs = Path(docs) if docs else None
    kept_docs = bool(docs and docs.is_file() and docs.stat().st_size > 0)
    if kept_docs:
        shutil.copyfile(docs, out / "docs" / "index.html")
    else:
        (out / "docs" / "index.html").write_text(NO_DOCS)
    return {"had_export": last_success is not None or (last / "manifest.json").is_file(), "kept_docs": kept_docs, "status": status}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m export.recover")
    ap.add_argument("--published", default="datastore/published")
    ap.add_argument("--out", default="public")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--failed-step", default="unknown")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--docs")
    ap.add_argument("--collected", choices=["true", "false"], help="whether the run's snapshots were stored before it failed")
    a = ap.parse_args(argv)
    r = recover(a.published, a.out, a.run_id, a.failed_step, a.run_url, a.docs,
                collected=None if a.collected is None else a.collected == "true")
    print(f"recovery site in {a.out}: last good export {'kept' if r['had_export'] else 'absent (none has succeeded yet)'}, "
          f"docs {'kept' if r['kept_docs'] else 'placeholder'}, failed at {a.failed_step!r} ({r['status']['failed_stage']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
