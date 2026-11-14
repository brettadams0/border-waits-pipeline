"""The export: contract, payload budget, retention, the saved-snapshot bundle and the failure site."""
import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

import duckdb
import pytest

from export import __main__ as export
from export import contract, recover


def load(d, summary=None):
    m = json.loads((d / "manifest.json").read_text())
    return m, json.loads((d / m["files"]["summary"]["url"]).read_text())


def test_files_match_their_hashes_and_the_contract(multiweek):
    m, s = load(multiweek.out)
    for name, f in m["files"].items():
        body = (multiweek.out / f["url"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == f["sha256"], name
        assert f["sha256"][:8] in f["url"] or name == "summary", name
    assert contract.problems(m, s) == []
    assert m["tests"]["error"] == 0
    assert m["rebuild_check"]["expected"] == export.rebuild_check(
        (multiweek.out / m["files"]["sql/agg_wait_by_hour"]["url"]).read_text(), multiweek.out / m["files"]["fct_wait_readings_recent"]["url"])
    assert "Open Government Licence – Canada" in (multiweek.out / "index.html").read_text()


def test_summary_stays_inside_its_budget_on_a_month_of_data(multiweek):
    """F08/D10: the old check (<= 30 kB) ran against one fixture run; the live summary was 66 kB.
    The summary is bounded by construction: featured series x 24 hours, one latest row per series,
    and nothing the page doesn't draw."""
    m, s = load(multiweek.out)
    body = (multiweek.out / m["files"]["summary"]["url"]).read_bytes()
    assert set(s) == {"run_id", "crossings", "latest", "by_hour", "chart"}   # last_48h was fetched and never drawn
    assert len(s["latest"]) == 3 * 2 * 2 and len(s["by_hour"]) == 3 * 2 * 2 * 24   # the fixture fills every cell: the maximum
    assert len(body) <= 64 * 1024, len(body)
    assert len(gzip.compress(body)) <= 8 * 1024, len(gzip.compress(body))
    assert s["chart"]["window_days"] == 28 and s["chart"]["min_days_band"] > s["chart"]["min_days_solid"] > s["chart"]["min_days_point"]
    # 30 days were stored; the window is 28 (a day spans two local dates at each end)
    assert 28 <= s["chart"]["days_with_readings"] <= 29, s["chart"]


def test_latest_is_one_whole_row_from_the_newest_poll(multiweek):
    _, s = load(multiweek.out)
    newest = datetime.fromisoformat(multiweek.runs[-1].replace("Z", "+00:00"))
    con = duckdb.connect(str(multiweek.work / "bwt.duckdb"), read_only=True)
    con.execute("set TimeZone = 'UTC'")
    for r in s["latest"]:
        stored = con.execute("""select status_raw, delay_min, is_open, source_updated_at::varchar from int_readings_matched
            where crossing_id = ? and direction = ? and lane = ? and fetched_at = ?""",
                             [r["crossing_id"], r["direction"], r["lane"], newest]).fetchall()
        assert stored == [(r["status_raw"], r["delay_min"], r["is_open"], r["source_updated_at"])], r
        assert datetime.fromisoformat(r["observed_at"] + ":00") == newest
    # CBP publishes a closed lane with no update time. It used to vanish from the tables, leaving the last
    # number on show; it is now the latest row, closed, with no number and no source time.
    closed = con.execute("select delay_min, source_updated_at, observed_at from latest_readings where source = 'cbp' and is_open = false").fetchall()
    assert closed and all(d is None and t is None and seen == newest for d, t, seen in closed), closed


def test_manifest_reports_health_per_source_and_the_real_cadence(multiweek):
    m, _ = load(multiweek.out)
    for s in ("cbsa", "cbp"):
        run = m["sources"][s]["last_run"]
        assert run["crossings"] >= 25 and run["timed_rows"] <= run["rows"]
        assert m["sources"][s]["lag_minutes"] == run["median_age_minutes"] >= 0   # never negative (D07)
    assert m["sources"]["cbp"]["last_run"]["stamped_ahead"] > 0                  # CBP's coming-hour stamps, counted, not hidden
    assert m["sources"]["cbp"]["last_run"]["timed_rows"] < m["sources"]["cbp"]["last_run"]["rows"]
    c = m["cadence"]
    assert c["runs_7d"] < 7 * 24 and c["median_gap_minutes_7d"] >= 60 and c["max_gap_minutes_7d"] >= c["median_gap_minutes_7d"]
    assert m["quality"]["excluded"] == [] and m["quality"]["fetch_timed_readings"] > 0
    assert all(d["text"] for d in m["tests"]["details"]), m["tests"]["details"]   # every warning has a plain-language line


@pytest.mark.parametrize("change, expect", [
    (lambda m, s: m.update(schema_version=2), "schema_version"),
    (lambda m, s: s.update(latest=None), "summary.latest"),
    (lambda m, s: s["latest"][0].update(delay_min="12"), "bad row"),
    (lambda m, s: s["latest"][0].update(direction="north"), "bad row"),
    (lambda m, s: s["latest"][0].update(source_updated_at="yesterday"), "bad row"),
    (lambda m, s: s["by_hour"][0].update(local_hour=24), "bad row"),
    (lambda m, s: m["files"].pop("summary"), "files.summary"),
    (lambda m, s: m["files"]["dim_crossing"].update(url="https://example.com/x.parquet"), "relative path"),
    (lambda m, s: m["files"]["dim_crossing"].update(url="../../x.parquet"), "relative path"),
    (lambda m, s: m["files"].update({"x; drop": {"url": "x.parquet"}}), "table name"),
    (lambda m, s: m.update(generated_at="soon"), "generated_at"),
])
def test_contract_rejects(multiweek, change, expect):
    m, s = load(multiweek.out)
    change(m, s)
    assert any(expect in p for p in contract.problems(m, s)), contract.problems(m, s)
    with pytest.raises(ValueError):
        contract.validate(m, s)


def test_contract_accepts_empty_and_older_exports(multiweek):
    m, s = load(multiweek.out)
    s.update(crossings=[], latest=[], by_hour=[])           # no readings yet: valid, the page says so
    assert contract.problems(m, s) == []
    m, s = load(multiweek.out)
    for r in s["latest"]:                                   # an export from before observed_at / valid_days existed
        r.pop("observed_at"), r.pop("source")
    for r in s["by_hour"]:
        r.pop("valid_days")
    s.pop("chart")
    assert contract.problems(m, s) == []


def test_no_readings_exports_an_empty_but_valid_summary(tmp_path):
    """A database whose tables exist but hold no readings (the first run, or everything quarantined)."""
    from tests.conftest import dbt_build
    hist = tmp_path / "ds" / "history" / "cbsa_land"
    hist.mkdir(parents=True)
    (hist / "2025-12-18T22:31:02.377918.csv").write_bytes((export.Path(__file__).resolve().parent.parent / "fixtures" / "cbsa-history.csv").read_bytes())
    from ingest.write import run_paths, write_parquet
    for source in ("cbsa", "cbp"):
        write_parquet([], run_paths(tmp_path / "ds", source, "2026-10-27T17:26:20Z")[0])
    # (a run like this fails its own tests, 25 crossings per source, and is never exported by the pipeline;
    # the models alone are built here to prove the export and the page's contract survive emptiness)
    p, _ = dbt_build(tmp_path, "", exclude=("tag:freshness", "test_type:data"))
    assert p.returncode == 0, p.stdout[-2000:]
    out = tmp_path / "out"
    assert export.main(["--run-id", "empty-1", "--db", str(tmp_path / "bwt.duckdb"), "--dbt-target", str(tmp_path / "target"),
                        "--out", str(out), "--datastore", str(tmp_path / "ds"), "--previous", str(tmp_path / "none")]) == 0
    m, s = load(out)
    assert s["latest"] == [] and s["by_hour"] == [] and len(s["crossings"]) == 3
    assert m["sources"]["cbp"]["freshness"] is None and m["files"]["fct_wait_readings"]["rows"] == 0


# ---- D03: retention ----

def generation(d, run, when, names):
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).parent.mkdir(parents=True, exist_ok=True)
        (d / n).write_text(n)
    return {"run_id": run, "generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "files": sorted(names)}


def test_retention_is_bounded_over_many_generations(tmp_path):
    """Forty hourly exports, each with new fact files and the same dim file. The old code copied the whole
    previous directory forward every time (584 files after 18 days); this keeps the window and nothing else."""
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    prev, counts, index = tmp_path / "none", [], []
    for i in range(40):
        out = tmp_path / f"gen{i}"
        g = generation(out, f"run{i}", t0 + timedelta(hours=i), [f"fct.{i:04d}.parquet", f"summary.run{i}.json", "dim.same.parquet", f"sql/model.{i // 10}.sql"])
        index = export.carry_over(prev, out, g, retain_hours=6, retain_max=12)
        (out / "retained.json").write_text(json.dumps(index))
        counts.append(sum(1 for p in out.rglob("*") if p.is_file()))
        # every retained generation, the current one included, still resolves
        for kept in index:
            assert all((out / f).is_file() for f in kept["files"]), kept["run_id"]
        prev = out
    assert [g["run_id"] for g in index] == [f"run{i}" for i in range(39, 32, -1)]   # this run + the 6 hours before it
    assert counts[-1] == 7 * 2 + 1 + 1 + 1                                          # 7 x (fct, summary) + dim + 1 sql + index
    assert max(counts) == counts[-1] + 1                                            # +1 while the window spans two sql versions
    assert not (prev / "fct.0031.parquet").exists() and (prev / "fct.0033.parquet").exists()
    assert (prev / "dim.same.parquet").read_text() == "dim.same.parquet"            # shared content is stored once


def test_retention_keeps_the_previous_generation_however_old_and_caps_the_count(tmp_path):
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    a = tmp_path / "a"
    ga = generation(a, "a", t0, ["fct.a.parquet"])
    (a / "retained.json").write_text(json.dumps([ga]))
    b = tmp_path / "b"   # the scheduler skipped a day: the one earlier generation is far outside the window
    index = export.carry_over(a, b, generation(b, "b", t0 + timedelta(hours=30), ["fct.b.parquet"]), 6, 12)
    assert [g["run_id"] for g in index] == ["b", "a"] and (b / "fct.a.parquet").exists()
    # a burst of runs inside the window: never more than retain_max generations
    prev = b
    (b / "retained.json").write_text(json.dumps(index))
    for i in range(20):
        out = tmp_path / f"c{i}"
        index = export.carry_over(prev, out, generation(out, f"c{i}", t0 + timedelta(hours=31, minutes=i), [f"fct.c{i}.parquet"]), 6, 5)
        (out / "retained.json").write_text(json.dumps(index))
        prev = out
    assert len(index) == 5 and sum(1 for p in prev.glob("*.parquet")) == 5


def test_retention_adopts_a_directory_from_before_the_index_and_ignores_strays(tmp_path):
    """The first run after this change meets a published/ directory holding every generation ever made
    and no retained.json. Only the files its manifest names come forward."""
    old = tmp_path / "old"
    generation(old, "old", datetime(2026, 11, 14, 17, tzinfo=timezone.utc), ["fct.now.parquet", "fct.ancient1.parquet", "fct.ancient2.parquet"])
    (old / "manifest.json").write_text(json.dumps({"run_id": "old", "generated_at": "2026-11-14T17:06:14Z",
                                                   "files": {"fct": {"url": "fct.now.parquet"}, "evil": {"url": "../outside.parquet"}}}))
    (tmp_path / "outside.parquet").write_text("x")
    out = tmp_path / "new"
    index = export.carry_over(old, out, generation(out, "new", datetime(2026, 11, 14, 19, tzinfo=timezone.utc), ["fct.new.parquet"]), 6, 12)
    assert sorted(p.name for p in out.glob("*.parquet")) == ["fct.new.parquet", "fct.now.parquet"]
    assert [g["run_id"] for g in index] == ["new", "old"] and not (tmp_path / "new" / ".." / "outside.parquet").resolve().parent == out


def test_second_export_shares_unchanged_files_and_first_generation_still_resolves(multiweek, tmp_path):
    out2 = tmp_path / "v1"
    args = [a if a != multiweek.run_id else multiweek.run_id + "-b" for a in multiweek.export_args]
    args[args.index("--generated-at") + 1] = "2026-11-14T19:00:00Z"
    assert export.main(args + ["--out", str(out2), "--previous", str(multiweek.out)]) == 0
    m1, _ = load(multiweek.out)
    m2, _ = load(out2)
    assert m2["retention"]["generations"] == 2
    for f in m1["files"].values():                          # a page that loaded before the second deploy
        assert (out2 / f["url"]).is_file(), f["url"]
    same = [k for k in m1["files"] if m1["files"][k]["url"] == m2["files"][k]["url"]]
    assert "fct_wait_readings" in same and "summary" not in same
    assert sum(1 for p in out2.glob("*.parquet")) == len(export.TABLES)   # identical content: stored once


# ---- D11: the saved snapshot ----

def test_bundle_is_a_complete_featured_only_export(multiweek):
    m, s = load(multiweek.bundle)
    assert contract.problems(m, s) == [] and m["sample"]["scope"] == "featured"
    assert m["files"]["summary"]["url"] == "summary.json" and json.loads((multiweek.bundle / "status.json").read_text())["result"] == "success"
    for name, f in m["files"].items():
        assert hashlib.sha256((multiweek.bundle / f["url"]).read_bytes()).hexdigest() == f["sha256"], name
    con = duckdb.connect()
    crossings = lambda t: {r[0] for r in con.execute(f"select distinct crossing_id from read_parquet('{multiweek.bundle / m['files'][t]['url']}')").fetchall()}
    for t in ("dim_crossing", "fct_wait_readings", "fct_wait_readings_recent", "latest_readings", "agg_wait_by_hour", "agg_wait_by_weekday_hour"):
        assert crossings(t) == {"ambassador_bridge", "detroit_windsor_tunnel", "gordie_howe_bridge"}, t
    # the rebuild check is recomputed over the bundle's own file, so the console's check works on the snapshot
    assert m["rebuild_check"]["expected"] == export.rebuild_check(
        (multiweek.bundle / m["rebuild_check"]["sql"]).read_text(), multiweek.bundle / m["rebuild_check"]["input"])
    full, _ = load(multiweek.out)
    assert m["rebuild_check"]["expected"] != full["rebuild_check"]["expected"]
    assert sum(p.stat().st_size for p in multiweek.bundle.rglob("*") if p.is_file()) < 300 * 1024


# ---- F06: what is published when a run fails ----

def test_recovery_site_keeps_data_and_docs(multiweek, tmp_path):
    published = tmp_path / "published"
    recover.shutil.copytree(multiweek.out, published / "data" / "v1")
    docs = tmp_path / "live-docs.html"
    docs.write_text("<html>the dbt docs that are live</html>")
    r = recover.recover(published, tmp_path / "public", "9-1", "dbt build", "https://example.test/run/9", docs, now="2026-11-14T20:00:00Z")
    out = tmp_path / "public"
    m, s = load(out / "data" / "v1")
    assert contract.problems(m, s) == []
    assert all((out / "data" / "v1" / f["url"]).is_file() for f in m["files"].values())   # every referenced file came along
    assert (out / "docs" / "index.html").read_text() == docs.read_text() and r["kept_docs"]
    st = json.loads((out / "data" / "v1" / "status.json").read_text())
    assert st == {"run_id": "9-1", "time": "2026-11-14T20:00:00Z", "result": "failure", "failed_step": "dbt build",
                  "failed_stage": "build", "collected": True, "run_url": "https://example.test/run/9",
                  "last_success": {"run_id": multiweek.run_id, "time": "2026-11-14T18:30:00Z", "result": "success"}}
    # a second failure in a row: the last success is still the last success
    published2 = tmp_path / "published2"
    recover.shutil.copytree(out / "data", published2 / "data")
    recover.recover(published2, tmp_path / "public2", "10-1", "Ingest", now="2026-11-14T21:00:00Z")
    st2 = json.loads((tmp_path / "public2" / "data" / "v1" / "status.json").read_text())
    assert st2["last_success"]["run_id"] == multiweek.run_id and st2["failed_stage"] == "collect" and st2["collected"] is False
    assert "next successful pipeline run" in (tmp_path / "public2" / "docs" / "index.html").read_text()   # no docs given: a placeholder, not a 404


def test_recovery_with_no_earlier_export_says_so(tmp_path):
    (tmp_path / "published").mkdir()
    assert recover.main(["--published", str(tmp_path / "published"), "--out", str(tmp_path / "public"), "--run-id", "1-1",
                         "--failed-step", "Ingest", "--docs", str(tmp_path / "missing.html")]) == 0
    v1 = tmp_path / "public" / "data" / "v1"
    st = json.loads((v1 / "status.json").read_text())
    assert st["result"] == "failure" and st["last_success"] is None and st["collected"] is False
    assert not (v1 / "manifest.json").exists()               # nothing pretends to be an export; the page falls back to its snapshot
    assert (v1 / "index.html").exists() and (tmp_path / "public" / "docs" / "index.html").exists()
