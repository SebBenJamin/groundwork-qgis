"""One-off, online: fetch the open data for the Vaud reflection demo.

Run: python-qgis.bat scripts/fetch_demo_vaud.py

Needs segyio (the trace positions say which elevation tiles to fetch); it is looked for in
.testlibs/ as the tests do (scripts/test.ps1 says how to put it there).

Writes the raw downloads to .cache/demo_seismic/swisstopo/ (git-ignored):
  vd-p760057.zip, vd-p760068.zip    the lines VD-P760057 and VD-P760068 from swisstopo's
                                    "2D and 3D reflection seismic in Switzerland" (opendata.swiss,
                                    free use, source: Federal Office of Topography swisstopo)
  x/<zip name>/<line>_stk-p.sgy     each zip's stack, unpacked (the TIFF and the PDF stay
                                    in the zip)
  swissalti3d/<tile>.tif            swissALTI3D 2 m tiles (swisstopo, same terms) that reach
                                    within 500 m of a line, from swisstopo's STAC catalogue
"""
from __future__ import annotations

import io
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import vaud_data

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "demo_seismic" / "swisstopo"
TILES = CACHE / "swissalti3d"
USER_AGENT = "groundwork-qgis-demo-builder/0.3 (QGIS plugin demo data; one-off fetch)"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def stack_path(line: str, cache: Path = CACHE) -> Path | None:
    """The unpacked stack of ``line`` under ``cache``/x/, None before fetching."""
    folder = cache / "x" / Path(vaud_data.zip_name(line)).stem
    hits = [p for p in folder.glob("*") if p.name.lower().endswith(vaud_data.STACK_SUFFIX)]
    return hits[0] if len(hits) == 1 else None


def fetch_line(line: str, cache: Path = CACHE) -> Path:
    """The line's zip (downloaded once) and its stack unpacked beside it."""
    target = cache / vaud_data.zip_name(line)
    if not (target.exists() and zipfile.is_zipfile(target)):
        cache.mkdir(parents=True, exist_ok=True)
        data = _get(vaud_data.BASE + vaud_data.LINES[line])
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise RuntimeError(f"{line}: the download is not a zip: {data[:200]!r}")
        target.write_bytes(data)
    found = stack_path(line, cache)
    if found is not None:
        return found
    with zipfile.ZipFile(target) as zf:
        member = vaud_data.stack_member(zf.namelist())
        if member is None:
            raise RuntimeError(f"{target.name} has no *{vaud_data.STACK_SUFFIX} "
                               f"(it holds {', '.join(zf.namelist())})")
        out = cache / "x" / target.stem / Path(member).name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zf.read(member))
    return out


def line_positions(path: Path):
    """The trace positions (n, 2) in LV95, as Add Data reads them."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / ".testlibs"))
    try:
        import segyio  # noqa: F401
    except ImportError:
        raise RuntimeError("segyio is missing; see scripts/test.ps1 for putting it into "
                           ".testlibs/") from None
    from groundwork_geophysics.readers import segy
    return segy.map_positions(path, vaud_data.OPTIONS)


def _wgs84_box(box) -> tuple[float, float, float, float]:
    from osgeo import osr
    osr.UseExceptions()
    src, dst = osr.SpatialReference(), osr.SpatialReference()
    src.ImportFromEPSG(2056)
    dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(src, dst)
    x0, y0, x1, y1 = box
    pts = [tr.TransformPoint(x, y)[:2] for x in (x0, x1) for y in (y0, y1)]
    lon, lat = [p[0] for p in pts], [p[1] for p in pts]
    return min(lon) - 0.01, min(lat) - 0.01, max(lon) + 0.01, max(lat) + 0.01


def stac_items(box) -> list[dict]:
    """Every swissALTI3D item in the WGS84 box around the LV95 ``box``, page by page."""
    url = vaud_data.STAC_ITEMS + "?" + urllib.parse.urlencode(
        {"bbox": ",".join(f"{v:.5f}" for v in _wgs84_box(box)), "limit": 100})
    items = []
    while url:
        page = json.loads(_get(url).decode("utf-8"))
        items += page.get("features", [])
        url = next((link["href"] for link in page.get("links", [])
                    if link.get("rel") == "next"), None)
    return items


def fetch_tiles(lines, tiles: Path = TILES) -> list[Path]:
    """The 2 m tiles within the corridor of ``lines``; stops when the catalogue lacks one."""
    need = vaud_data.tiles_near(lines)
    have = {key: tiles / f"{key[0]}-{key[1]}.tif" for key in need}
    missing = [k for k, p in have.items() if not (p.exists() and p.stat().st_size > 0)]
    if missing:
        hrefs = vaud_data.newest_tiles(stac_items(vaud_data.corridor_box(lines)))
        absent = [k for k in missing if k not in hrefs]
        if absent:
            raise RuntimeError(f"swissALTI3D has no 2 m tile for {absent[:5]}")
        tiles.mkdir(parents=True, exist_ok=True)
        for key in missing:
            data = _get(hrefs[key])
            if data[:2] not in (b"II", b"MM"):
                raise RuntimeError(f"swissALTI3D tile {key} is not a GeoTIFF: {data[:200]!r}")
            have[key].write_bytes(data)
    return [have[k] for k in need]


def main() -> int:
    from groundwork_geophysics.core.lines import line_from_cloud
    stacks = {line: fetch_line(line) for line in vaud_data.LINES}
    lines = [line_from_cloud(line_positions(p))[0] for p in stacks.values()]
    tiles = fetch_tiles(lines)
    print(f"{CACHE}: {', '.join(p.name for p in stacks.values())}, {len(tiles)} swissALTI3D "
          f"tiles")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
