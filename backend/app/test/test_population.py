from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.spatial.adapters.population import (
    PopulationExposureAdapter,
)


def _write_raster(
    path: Path,
    data: np.ndarray,
    *,
    dtype: str,
    nodata: float | None = None,
) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=dtype,
        crs="EPSG:4326",
        transform=from_origin(
            72.0,
            20.0,
            0.01,
            0.01,
        ),
        nodata=nodata,
    ) as dst:
        dst.write(data.astype(dtype), 1)


def test_population_adapter_calculates_fractional_exposure(
    tmp_path: Path,
) -> None:
    population = tmp_path / "population.tif"
    flood = tmp_path / "flood.tif"

    # Four population cells, 100 people each.
    _write_raster(
        population,
        np.full((2, 2), 100, dtype=np.float32),
        dtype="float32",
    )

    # Half of each population cell is flooded.
    flood_data = np.array(
        [
            [1, 0],
            [1, 0],
        ],
        dtype=np.uint8,
    )
    _write_raster(
        flood,
        flood_data,
        dtype="uint8",
    )

    result = PopulationExposureAdapter(
        population_path=population,
        flood_mask_path=flood,
    ).calculate()

    assert result.source == "WorldPop + Sentinel-1"
    assert result.population_dataset == "population.tif"
    assert result.flood_mask_dataset == "flood.tif"

    # With identical grids, two of four cells are fully flooded.
    assert result.population_at_risk == 200.0
    assert 0.0 < result.flooded_area_sq_km
    assert result.affected_population_percentage == 50.0


def test_population_adapter_handles_nodata(
    tmp_path: Path,
) -> None:
    population = tmp_path / "population.tif"
    flood = tmp_path / "flood.tif"

    population_data = np.array(
        [
            [100, -9999],
            [100, 100],
        ],
        dtype=np.float32,
    )

    _write_raster(
        population,
        population_data,
        dtype="float32",
        nodata=-9999,
    )

    _write_raster(
        flood,
        np.ones((2, 2), dtype=np.uint8),
        dtype="uint8",
    )

    result = PopulationExposureAdapter(
        population_path=population,
        flood_mask_path=flood,
    ).calculate()

    assert result.population_at_risk == 300.0
    assert result.affected_population_percentage == 100.0


def test_population_adapter_requires_population_raster(
    tmp_path: Path,
) -> None:
    flood = tmp_path / "flood.tif"

    _write_raster(
        flood,
        np.ones((2, 2), dtype=np.uint8),
        dtype="uint8",
    )

    missing_population = tmp_path / "missing_population.tif"

    try:
        PopulationExposureAdapter(
            population_path=missing_population,
            flood_mask_path=flood,
        )
    except FileNotFoundError:
        return

    raise AssertionError(
        "Expected FileNotFoundError for missing population raster."
    )


def test_population_adapter_requires_flood_raster(
    tmp_path: Path,
) -> None:
    population = tmp_path / "population.tif"

    _write_raster(
        population,
        np.full((2, 2), 100, dtype=np.float32),
        dtype="float32",
    )

    missing_flood = tmp_path / "missing_flood.tif"

    try:
        PopulationExposureAdapter(
            population_path=population,
            flood_mask_path=missing_flood,
        )
    except FileNotFoundError:
        return

    raise AssertionError(
        "Expected FileNotFoundError for missing flood raster."
    )
