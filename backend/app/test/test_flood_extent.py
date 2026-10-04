from pathlib import Path

import pytest

from app.spatial.adapters.flood_extent import (
    FloodExtentAdapter,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]

FLOOD_EXTENT_RASTER = (
    PROJECT_ROOT
    / "data"
    / "flood_extent"
    / "mumbai_s1_flood_extent.tif"
)


@pytest.fixture
def adapter() -> FloodExtentAdapter:
    return FloodExtentAdapter(FLOOD_EXTENT_RASTER)


def test_flood_extent_raster_exists() -> None:
    assert FLOOD_EXTENT_RASTER.exists()


def test_flood_extent_sample(adapter: FloodExtentAdapter) -> None:
    result = adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    assert result.source == "Sentinel-1"
    assert result.dataset == "mumbai_s1_flood_extent.tif"

    assert 0.0 <= result.flood_extent_value <= 1.0
    assert 0.0 <= result.flood_extent_risk <= 1.0

    assert result.flooded_area_sq_km > 0.0


def test_flood_extent_area_is_reasonable(
    adapter: FloodExtentAdapter,
) -> None:
    result = adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    # Current validated Sentinel-1 raster is approximately
    # 1.896 km² after projected-area calculation.
    assert 1.0 < result.flooded_area_sq_km < 3.0


def test_flood_extent_risk_zero(
    adapter: FloodExtentAdapter,
) -> None:
    assert adapter._flood_extent_risk(0.0) == 0.0


def test_flood_extent_risk_one(
    adapter: FloodExtentAdapter,
) -> None:
    assert adapter._flood_extent_risk(1.0) == 1.0


def test_flood_extent_risk_clamped(
    adapter: FloodExtentAdapter,
) -> None:
    assert adapter._flood_extent_risk(-1.0) == 0.0
    assert adapter._flood_extent_risk(2.0) == 1.0


def test_location_outside_raster(
    adapter: FloodExtentAdapter,
) -> None:
    with pytest.raises(ValueError):
        adapter.sample(
            latitude=20.0,
            longitude=75.0,
        )