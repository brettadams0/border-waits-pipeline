"""Chart the published wait readings for the three Windsor–Detroit crossings.

Run once; the output is what gets committed.

    python tools/chart_waits.py               # fetch the live export, write CSV + both SVGs
    python tools/chart_waits.py --from-csv    # re-render the SVGs from the committed CSV

Reads fct_wait_readings from the published export named by the live manifest,
writes the plotted rows to results/waits.csv, and draws results/waits-light.svg
and results/waits-dark.svg by hand (no plotting library).

Every reading is a marker, and every pipeline run is a tick on the strip above
each panel, so the gaps between runs are visible as gaps. A line joins two
readings only when they come from consecutive runs less than GAP_MINUTES
apart; nothing is drawn across a longer stretch. GitHub drops scheduled runs,
and a chart that drew through those gaps would show readings never taken.
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "results" / "waits.csv"
DATA = "https://brettadams0.github.io/border-waits-pipeline/data/v1/"

# The cron schedule is :17 and :47; 90 minutes means at least two scheduled
# runs in a row did not happen.
GAP_MINUTES = 90
# All three featured crossings sit on the Detroit River; times are local there.
ZONE = ZoneInfo("America/Toronto")

CROSSINGS = [
    ("ambassador_bridge", "Ambassador Bridge"),
    ("detroit_windsor_tunnel", "Detroit–Windsor Tunnel"),
    ("gordie_howe_bridge", "Gordie Howe Bridge"),
]
PANELS = [
    ("to_us", "travellers", "To the US · travellers"),
    ("to_us", "commercial", "To the US · commercial"),
    ("to_canada", "travellers", "To Canada · travellers"),
    ("to_canada", "commercial", "To Canada · commercial"),
]

THEMES = {
    "light": {
        "bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e", "grid": "#d8dee4",
        "series": ["#0969da", "#bc4c00", "#1a7f37"],
    },
    "dark": {
        "bg": "#0d1117", "fg": "#e6edf3", "muted": "#9198a1", "grid": "#30363d",
        "series": ["#4493f8", "#f0883e", "#3fb950"],
    },
}

WIDTH = 720
MARGIN_L, MARGIN_R, MARGIN_T, GUTTER_X, GUTTER_Y = 44, 16, 64, 30, 64
PANEL_W, PANEL_H = (WIDTH - MARGIN_L - MARGIN_R - GUTTER_X) // 2, 150
STRIP_H = 8  # run strip above each panel
# Drawn largest first, so readings that coincide show as concentric rings.
MARKER_R = [4.6, 3.3, 2.0]


# ---------------------------------------------------------------- data ------

def fetch_rows() -> tuple[list[dict], dict]:
    import duckdb  # only needed when fetching; --from-csv runs on the stdlib

    manifest = json.load(urllib.request.urlopen(DATA + "manifest.json"))
    url = DATA + manifest["files"]["fct_wait_readings"]["url"]
    con = duckdb.connect()
    con.sql("install httpfs; load httpfs; set timezone = 'UTC'")
    ids = ", ".join(f"'{c}'" for c, _ in CROSSINGS)
    runs = con.sql(f"select distinct run_id, fetched_at from '{url}' order by fetched_at").fetchall()
    readings = con.sql(
        f"select run_id, crossing_id, direction, lane, delay_min from '{url}' "
        f"where crossing_id in ({ids}) and lane_type = 'standard' and delay_min is not null"
    ).fetchall()
    by_run = {run_id: fetched for run_id, fetched in runs}
    rows = [
        {"run_id": r, "fetched_at": by_run[r].isoformat(), "crossing_id": c,
         "direction": d, "lane": lane, "delay_min": m}
        for r, c, d, lane, m in readings
    ]
    # Runs with no featured reading still prove the pipeline ran; keep them.
    for run_id, fetched in runs:
        rows.append({"run_id": run_id, "fetched_at": fetched.isoformat(), "crossing_id": "",
                     "direction": "", "lane": "", "delay_min": ""})
    rows.sort(key=lambda r: (r["fetched_at"], r["crossing_id"], r["direction"], r["lane"]))
    meta = {"generated_at": manifest["generated_at"], "data_sha": manifest["data_sha"], "file": url}
    return rows, meta


def write_csv(rows: list[dict], meta: dict) -> None:
    CSV_PATH.parent.mkdir(exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        f.write(f"# source: {meta['file']}\n# export generated_at: {meta['generated_at']} data_sha: {meta['data_sha']}\n")
        w = csv.DictWriter(f, fieldnames=["run_id", "fetched_at", "crossing_id", "direction", "lane", "delay_min"])
        w.writeheader()
        w.writerows(rows)


def read_csv() -> tuple[list[dict], dict]:
    lines = CSV_PATH.read_text(encoding="utf-8").splitlines()
    meta = {"file": lines[0].split(": ", 1)[1],
            "generated_at": lines[1].split()[3], "data_sha": lines[1].split()[5]}
    return list(csv.DictReader(lines[2:])), meta


# -------------------------------------------------------------- render ------

def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(rows: list[dict], meta: dict, theme: dict) -> str:
    runs = sorted({datetime.fromisoformat(r["fetched_at"]) for r in rows})
    t0, t1 = runs[0], runs[-1]
    span = (t1 - t0).total_seconds()
    readings = [r for r in rows if r["crossing_id"]]
    y_max = max(10, max(int(r["delay_min"]) for r in readings))
    y_max = -(-y_max // 10) * 10
    run_index = {t: i for i, t in enumerate(runs)}

    rows_n = len(PANELS) // 2
    height = MARGIN_T + rows_n * (PANEL_H + STRIP_H + 4) + (rows_n - 1) * GUTTER_Y + 76
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}" '
        f'font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">',
        f'<rect width="{WIDTH}" height="{height}" fill="{theme["bg"]}"/>',
        f'<text x="{MARGIN_L}" y="22" font-size="15" font-weight="600" fill="{theme["fg"]}">'
        f'Published wait estimates, Windsor–Detroit, minutes</text>',
    ]
    # Legend.
    lx = MARGIN_L
    for (_, name), colour in zip(CROSSINGS, theme["series"]):
        out.append(f'<circle cx="{lx + 4}" cy="40" r="4" fill="{colour}"/>'
                   f'<text x="{lx + 13}" y="44" fill="{theme["fg"]}">{esc(name)}</text>')
        lx += 13 + 7.2 * len(name) + 22
    out.append(f'<line x1="{lx + 4}" x2="{lx + 4}" y1="34" y2="46" stroke="{theme["muted"]}" stroke-width="1.5"/>'
               f'<text x="{lx + 12}" y="44" fill="{theme["fg"]}">one pipeline run</text>')

    for p, (direction, lane, title) in enumerate(PANELS):
        px = MARGIN_L + (p % 2) * (PANEL_W + GUTTER_X)
        py = MARGIN_T + (p // 2) * (PANEL_H + STRIP_H + 4 + GUTTER_Y) + 18 + STRIP_H + 4

        def x(t: datetime, px: int = px) -> float:
            return px + (t - t0).total_seconds() / span * PANEL_W

        def y(m: float, py: int = py) -> float:
            return py + PANEL_H - m / y_max * PANEL_H

        out.append(f'<text x="{px}" y="{py - STRIP_H - 10}" font-weight="600" fill="{theme["fg"]}">{esc(title)}</text>')
        for t in runs:
            out.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{py - STRIP_H - 3}" y2="{py - 3}" '
                       f'stroke="{theme["muted"]}" stroke-width="1.5"/>')
        for m in range(0, y_max + 1, max(10, y_max // 4 // 10 * 10)):
            out.append(f'<line x1="{px}" x2="{px + PANEL_W}" y1="{y(m):.1f}" y2="{y(m):.1f}" stroke="{theme["grid"]}"/>'
                       f'<text x="{px - 6}" y="{y(m) + 4:.1f}" text-anchor="end" fill="{theme["muted"]}">{m}</text>')
        # Midnight ticks, local time.
        day = t0.astimezone(ZONE).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        while day <= t1:
            out.append(f'<line x1="{x(day):.1f}" x2="{x(day):.1f}" y1="{py}" y2="{py + PANEL_H + 4}" stroke="{theme["grid"]}"/>'
                       f'<text x="{x(day):.1f}" y="{py + PANEL_H + 17}" text-anchor="middle" fill="{theme["muted"]}">'
                       f'{day:%a %b} {day.day}</text>')
            day += timedelta(days=1)

        for (cid, _), colour, radius in zip(CROSSINGS, theme["series"], MARKER_R):
            pts = sorted(
                (datetime.fromisoformat(r["fetched_at"]), int(r["delay_min"]))
                for r in readings
                if r["crossing_id"] == cid and r["direction"] == direction and r["lane"] == lane
            )
            for (ta, ma), (tb, mb) in zip(pts, pts[1:]):
                if run_index[tb] - run_index[ta] == 1 and tb - ta <= timedelta(minutes=GAP_MINUTES):
                    out.append(f'<line x1="{x(ta):.1f}" y1="{y(ma):.1f}" x2="{x(tb):.1f}" y2="{y(mb):.1f}" '
                               f'stroke="{colour}" stroke-width="1.5"/>')
            for t, m in pts:
                out.append(f'<circle cx="{x(t):.1f}" cy="{y(m):.1f}" r="{radius}" fill="{colour}" '
                           f'stroke="{theme["bg"]}" stroke-width="0.8"/>')

    foot = height - 12
    first = t0.astimezone(ZONE).strftime("%Y-%m-%d %H:%M")
    last = t1.astimezone(ZONE).strftime("%Y-%m-%d %H:%M %Z")
    out.append(f'<text x="{MARGIN_L}" y="{foot}" fill="{theme["muted"]}" font-size="11">'
               f'{len(runs)} pipeline runs, {first} to {last}. Export data_sha {meta["data_sha"][:12]}. '
               f'Sources: CBSA, U.S. CBP.</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-csv", action="store_true", help="re-render from results/waits.csv")
    args = ap.parse_args()
    if args.from_csv:
        rows, meta = read_csv()
    else:
        rows, meta = fetch_rows()
        write_csv(rows, meta)
        rows, meta = read_csv()  # render from exactly what was committed
    for name, theme in THEMES.items():
        (ROOT / "results" / f"waits-{name}.svg").write_text(render(rows, meta, theme), encoding="utf-8")


if __name__ == "__main__":
    main()
