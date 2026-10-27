from pathlib import Path

from ingest import history

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def fake_download(url):
    assert "open.canada.ca/data/dataset/000fe5aa" in url
    return (FIX / "cbsa-history.csv").read_bytes(), {}


def test_downloads_once_per_metadata_modified(tmp_path):
    pkg = (FIX / "ckan-package_show.json").read_bytes()
    first = history.update(tmp_path, pkg, fake_download)
    assert first.name == "2025-12-18T22:31:02.377918.csv"
    assert first.read_bytes() == (FIX / "cbsa-history.csv").read_bytes()
    assert history.update(tmp_path, pkg, fake_download) is None
