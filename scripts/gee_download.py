"""Download a small set of reusable flood-risk rasters from Google Earth Engine.

Requires a registered Earth Engine Cloud project, prior authentication, and the
optional dependencies in scripts/requirements-gee.txt. GeoTIFF downloads made
through getDownloadURL are intentionally limited to small, single-request AOIs.
For larger regions, replace this transport with an Earth Engine batch export to
Cloud Storage rather than splitting silently or exhausting memory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "gee_downloads"
DEFAULT_BOUNDS = (72.76, 18.89, 73.20, 19.32)  # Mumbai Suburban vicinity; use --aoi for a precise boundary.


def load_bounds(aoi_path: Path | None) -> list[list[list[float]]]:
    if not aoi_path:
        west, south, east, north = DEFAULT_BOUNDS
        return [[[west, south], [east, south], [east, north], [west, north], [west, south]]]
    payload = json.loads(aoi_path.read_text(encoding="utf-8"))
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features", [])
        if len(features) != 1:
            raise ValueError("AOI FeatureCollection must contain exactly one Polygon feature")
        payload = features[0].get("geometry", {})
    elif payload.get("type") == "Feature":
        payload = payload.get("geometry", {})
    if payload.get("type") != "Polygon":
        raise ValueError("AOI must be a Polygon GeoJSON in EPSG:4326")
    return payload["coordinates"]


def datasets(ee, geometry, start: str, end: str):
    sentinel = (ee.ImageCollection("COPERNICUS/S1_GRD")
                .filterBounds(geometry).filterDate(start, end)
                .filter(ee.Filter.eq("instrumentMode", "IW"))
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
                .select("VV"))
    imerg = (ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
             .filterBounds(geometry).filterDate(start, end)
             .select("precipitation"))
    return {
        "sentinel1_vv_median": {"image": sentinel.median().rename("vv_db"), "scale": 10, "units": "dB", "source": "COPERNICUS/S1_GRD", "reducer": "median VV backscatter"},
        "imerg_precipitation_sum": {"image": imerg.sum().rename("precipitation_mm_hr_sum"), "scale": 11132, "units": "mm/hr accumulated values", "source": "NASA/GPM_L3/IMERG_V07", "reducer": "sum of precipitation band over selected period"},
        "nasadem_elevation": {"image": ee.Image("NASA/NASADEM_HGT/001").select("elevation"), "scale": 30, "units": "m", "source": "NASA/NASADEM_HGT/001", "reducer": "elevation"},
        "jrc_water_occurrence": {"image": ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence"), "scale": 30, "units": "% occurrence", "source": "JRC/GSW1_4/GlobalSurfaceWater", "reducer": "occurrence"},
        "worldpop_population": {"image": ee.ImageCollection("WorldPop/GP/100m/pop").filterBounds(geometry).filterDate("2020-01-01", "2021-01-01").mosaic().select("population"), "scale": 100, "units": "people per pixel", "source": "WorldPop/GP/100m/pop", "reducer": "mosaic (2020)", "note": "The collection may not include every country/year; check image availability for your AOI."},
    }


def download(image, geometry, output: Path, scale: int) -> None:
    url = image.clip(geometry).getDownloadURL({"region": geometry, "scale": scale, "crs": "EPSG:4326", "format": "GEO_TIFF", "filePerBand": False})
    with urlopen(url, timeout=180) as response:  # noqa: S310 - URL is returned by the authenticated EE API.
        data = response.read()
    if data[:2] == b"PK":
        temporary = output.with_suffix(".zip")
        temporary.write_bytes(data)
        with zipfile.ZipFile(temporary) as archive:
            tiffs = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if len(tiffs) != 1:
                raise RuntimeError(f"Expected one GeoTIFF in Earth Engine archive, found {len(tiffs)}")
            output.write_bytes(archive.read(tiffs[0]))
        temporary.unlink(missing_ok=True)
    else:
        output.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("EARTHENGINE_PROJECT"), help="Registered Google Cloud / Earth Engine project ID")
    parser.add_argument("--aoi", type=Path, help="Single Polygon GeoJSON boundary in EPSG:4326")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output folder (defaults to data/gee_downloads)")
    parser.add_argument("--start", default="2024-07-01", help="Start date inclusive (YYYY-MM-DD), used for Sentinel-1 and IMERG")
    parser.add_argument("--end", default="2024-09-01", help="End date exclusive (YYYY-MM-DD), used for Sentinel-1 and IMERG")
    parser.add_argument("--layers", nargs="+", choices=["sentinel1_vv_median", "imerg_precipitation_sum", "nasadem_elevation", "jrc_water_occurrence", "worldpop_population"], default=["sentinel1_vv_median", "imerg_precipitation_sum", "nasadem_elevation", "jrc_water_occurrence", "worldpop_population"])
    args = parser.parse_args()
    if not args.project:
        parser.error("Pass --project or set EARTHENGINE_PROJECT")
    if datetime.fromisoformat(args.start) >= datetime.fromisoformat(args.end):
        parser.error("--start must precede --end")
    try:
        import ee
    except ImportError:
        print("Install scripts/requirements-gee.txt before running this downloader.", file=sys.stderr)
        return 2

    ee.Initialize(project=args.project)
    aoi_coordinates = load_bounds(args.aoi)
    geometry = ee.Geometry.Polygon(aoi_coordinates)
    available = datasets(ee, geometry, args.start, args.end)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "project": args.project, "aoi": {"type": "Polygon", "coordinates": aoi_coordinates}, "period": {"start": args.start, "end_exclusive": args.end}, "datasets": {}}
    for name in args.layers:
        item = available[name]
        output = args.output / f"{name}.tif"
        print(f"Downloading {name} at {item['scale']} m → {output}")
        try:
            download(item["image"], geometry, output, item["scale"])
        except Exception as exc:
            raise RuntimeError(f"{name} download failed. getDownloadURL supports small requests (32 MB / 10,000-pixel grid limits); use an EE batch export for larger AOIs. Original error: {exc}") from exc
        manifest["datasets"][name] = {"file": output.name, "scale_m": item["scale"], "units": item["units"], "source": item["source"], "reducer": item["reducer"], "bytes": output.stat().st_size, "note": item.get("note")}
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
