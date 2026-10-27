"""python -m ingest --run-id RUN_ID [--fixtures] [--datastore DIR] [--raw-dir DIR] [--fetched-at ISO]"""
import argparse
import sys
from datetime import datetime, timezone

from . import cbp, cbsa, fetch
from .checks import run_checks
from .write import write_run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ingest")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--fixtures", action="store_true", help="read fixtures/ instead of the network")
    ap.add_argument("--datastore", default="datastore")
    ap.add_argument("--raw-dir", default="raw-artifact")
    ap.add_argument("--fetched-at", help="override the run time (tests)")
    a = ap.parse_args(argv)
    fetched_at = a.fetched_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bodies = {s: fetch.get(s, a.raw_dir, a.fixtures) for s in fetch.SOURCES}
    try:
        rows = {"cbsa": cbsa.parse(bodies["cbsa"], a.run_id, fetched_at),
                "cbp": cbp.parse(bodies["cbp"], a.run_id, fetched_at)}
    except cbsa.ContractError as e:
        print(f"contract failure: {e}", file=sys.stderr)
        return 1
    failures = run_checks(rows["cbsa"] + rows["cbp"])
    if failures:
        print("per-run checks failed; nothing written:", *failures, sep="\n  ", file=sys.stderr)
        return 1
    for path in write_run(rows, bodies["cbsa"], a.datastore, fetched_at):
        print(path)
    print(f"cbsa {len(rows['cbsa'])} rows, cbp {len(rows['cbp'])} rows, fetched_at {fetched_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
