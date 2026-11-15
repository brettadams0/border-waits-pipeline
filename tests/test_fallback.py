"""The committed saved snapshot (web/fallback/) is a real export the page and its console can use."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from export import snapshot_check

FALLBACK = Path(__file__).resolve().parent.parent / "web" / "fallback"


def test_committed_snapshot_is_complete_and_drawable():
    """Nothing here depends on today's date: an old checkout keeps passing. The age is a release check
    (python -m export.snapshot_check --max-age-days N), not a unit test."""
    problems, facts = snapshot_check.check(FALLBACK)
    assert problems == [], problems
    # the snapshot it replaced had n = 1 in every hour, so its chart drew nothing
    assert facts["drawable_hours"] >= 24 and facts["bytes"] < 300 * 1024, facts
    m = json.loads((FALLBACK / "manifest.json").read_text())
    assert m["data_sha"] and m["sample"]["scope"] == "featured"   # provenance: which data-branch commit it was built from


def test_snapshot_check_catches_damage_and_age(multiweek, tmp_path):
    import shutil
    good = tmp_path / "good"
    shutil.copytree(multiweek.bundle, good)
    assert snapshot_check.check(good)[0] == []
    newest = datetime(2026, 11, 14, 18, 26, 20, tzinfo=timezone.utc)
    assert snapshot_check.check(good, max_age_days=14, now=newest + timedelta(days=3))[0] == []
    old = snapshot_check.check(good, max_age_days=14, now=newest + timedelta(days=30))[0]
    assert len(old) == 1 and "30.0 days old" in old[0]
    (good / "stray.parquet").write_text("left over")
    assert any("does not name" in p for p in snapshot_check.check(good)[0])
    (good / "stray.parquet").unlink()
    m = json.loads((good / "manifest.json").read_text())
    (good / m["files"]["dim_crossing"]["url"]).write_bytes(b"truncated")
    assert any("does not match its sha256" in p for p in snapshot_check.check(good)[0])
