"""Disaster Risk Intelligence backend application package."""

from __future__ import annotations

import os


def _prefer_bundled_proj_data() -> None:
    """Avoid a stale PostGIS PROJ database on Windows PATH."""
    try:
        from pyproj import datadir
    except Exception:
        return

    proj_dir = datadir.get_data_dir()
    if not proj_dir:
        return

    os.environ["PROJ_DATA"] = proj_dir
    os.environ["PROJ_LIB"] = proj_dir
    datadir.set_data_dir(proj_dir)


_prefer_bundled_proj_data()

