"""Gülpe fetch script: the pure parts only (no network in tests)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def test_dgm_tiles_cover_bbox_with_margin():
    from fetch_demo_guelpe import dgm_tiles
    assert dgm_tiles((311673, 5845638, 312216, 5846564)) == [
        "dgm_33311-5845", "dgm_33311-5846", "dgm_33312-5845", "dgm_33312-5846"]


def test_is_zip_rejects_tape_page():
    from fetch_demo_guelpe import is_zip
    assert is_zip(b"PK\x03\x04rest") and not is_zip(b"<!DOCTYPE html>loading from tape")


def test_waterways_query_names_bbox_and_types():
    from fetch_demo_guelpe import waterways_query
    q = waterways_query((12.205, 52.725, 12.225, 52.740))
    assert "52.725,12.205,52.74,12.225" in q and "waterway" in q and "out geom" in q
