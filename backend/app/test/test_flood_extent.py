from pathlib import Path
import pytest
from app.spatial.adapters.flood_extent import FloodExtentAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[3]

FLOOD_EXTENT_PATH = (
    PROJECT_ROOT
    / "data"
    / "flood_extent"
    / "mumbai_s1_flood_extent.tif"
)


@pytest.fixture
def flood_extent_adapter() -> FloodExtentAdapter:
    return FloodExtentAdapter(
        FLOOD_EXTENT_PATH
    )


def test_flood_extent_file_exists() -> None:
    assert FLOOD_EXTENT_PATH.exists()


def test_flood_extent_sample_returns_valid_result(
    flood_extent_adapter: FloodExtentAdapter,
) -> None:
    result = flood_extent_adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    assert result.latitude == 19.076
    assert result.longitude == 72.8777

    assert 0.0 <= result.flood_extent_value <= 1.0
    assert 0.0 <= result.flood_extent_risk <= 1.0

    assert result.flooded_area_sq_km >= 0.0

    assert result.source == "Sentinel-1"

    assert (
        result.dataset
        == "mumbai_s1_flood_extent.tif"
    )


def test_flood_extent_resolution(
    flood_extent_adapter: FloodExtentAdapter,
) -> None:
    result = flood_extent_adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    assert result.resolution_x > 0
    assert result.resolution_y > 0


def test_flood_extent_outside_raster(
    flood_extent_adapter: FloodExtentAdapter,
) -> None:
    with pytest.raises(ValueError):
        flood_extent_adapter.sample(
            latitude=28.6139,
            longitude=77.2090,
        )


def test_flooded_area_is_non_negative(
    flood_extent_adapter: FloodExtentAdapter,
) -> None:
    result = flood_extent_adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    assert result.flooded_area_sq_km >= 0.0