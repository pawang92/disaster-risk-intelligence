"""Disaster Risk Intelligence backend application package."""

import os
from importlib.util import find_spec
from pathlib import Path


def _use_bundled_gis_data() -> None:
    """Avoid mixing Rasterio's PROJ/GDAL libraries with GIS paths from the OS.

    Windows GIS installations often set PROJ_LIB/GDAL_DATA globally. Those
    paths can point at an older PostgreSQL/PostGIS PROJ database and make
    Rasterio reject EPSG codes. Prefer the matching data shipped in the active
    Python environment when Rasterio is installed.
    """
    spec = find_spec("rasterio")
    if not spec or not spec.submodule_search_locations:
        return

    rasterio_root = Path(next(iter(spec.submodule_search_locations)))
    proj_data = rasterio_root / "proj_data"
    gdal_data = rasterio_root / "gdal_data"
    if (proj_data / "proj.db").is_file():
        os.environ["PROJ_LIB"] = str(proj_data)
        os.environ["PROJ_DATA"] = str(proj_data)
    if gdal_data.is_dir():
        os.environ["GDAL_DATA"] = str(gdal_data)


_use_bundled_gis_data()
