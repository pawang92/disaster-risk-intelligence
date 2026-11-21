from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from app.spatial.adapters.building import BuildingExposureAdapter


def _write_flood_raster(path: Path, data: np.ndarray) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(72.0, 20.0, 0.01, 0.01),
        nodata=0,
    ) as dst:
        dst.write(data.astype("uint8"), 1)


def _write_buildings(path: Path) -> None:
    buildings = gpd.GeoDataFrame(
        {
            "building_id": ["b1", "b2", "b3"],
        },
        geometry=[
            box(72.001, 19.999, 72.004, 19.996),
            box(72.011, 19.999, 72.014, 19.996),
            box(72.021, 19.999, 72.024, 19.996),
        ],
        crs="EPSG:4326",
    )
    buildings.to_file(path, driver="GeoJSON")


def test_building_adapter_calculates_flood_exposure(tmp_path: Path) -> None:
    flood = tmp_path / "flood.tif"
    buildings = tmp_path / "buildings.geojson"

    # Leftmost raster cell is flooded.
    _write_flood_raster(
        flood,
        np.array(
            [
                [1, 0, 0],
                [0, 0, 0],
                [0, 0, 0],
            ],
            dtype=np.uint8,
        ),
    )
    _write_buildings(buildings)

    result = BuildingExposureAdapter(
        building_path=buildings,
        flood_mask_path=flood,
    ).calculate()

    assert result.source == "Building footprints + Sentinel-1"
    assert result.building_dataset == "buildings.geojson"
    assert result.flood_mask_dataset == "flood.tif"
    assert result.total_buildings_in_analysis_area == 3
    assert result.buildings_at_risk == 1
    assert result.affected_building_percentage == round(100 / 3, 2)


def test_building_adapter_returns_zero_for_empty_flood(tmp_path: Path) -> None:
    flood = tmp_path / "flood.tif"
    buildings = tmp_path / "buildings.geojson"

    _write_flood_raster(
        flood,
        np.zeros((3, 3), dtype=np.uint8),
    )
    _write_buildings(buildings)

    result = BuildingExposureAdapter(
        building_path=buildings,
        flood_mask_path=flood,
    ).calculate()

    assert result.buildings_at_risk == 0
    assert result.total_buildings_in_analysis_area == 0
    assert result.affected_building_percentage == 0.0


def test_building_adapter_requires_building_dataset(tmp_path: Path) -> None:
    flood = tmp_path / "flood.tif"
    _write_flood_raster(
        flood,
        np.zeros((2, 2), dtype=np.uint8),
    )

    missing = tmp_path / "missing.geojson"

    try:
        BuildingExposureAdapter(
            building_path=missing,
            flood_mask_path=flood,
        )
    except FileNotFoundError:
        return

    raise AssertionError("Expected FileNotFoundError for missing buildings.")


def test_building_adapter_requires_flood_dataset(tmp_path: Path) -> None:
    buildings = tmp_path / "buildings.geojson"
    _write_buildings(buildings)

    missing = tmp_path / "missing.tif"

    try:
        BuildingExposureAdapter(
            building_path=buildings,
            flood_mask_path=missing,
        )
    except FileNotFoundError:
        return

    raise AssertionError("Expected FileNotFoundError for missing flood mask.")
