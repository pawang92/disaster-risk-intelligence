from pathlib import Path

import pytest

from app.spatial.adapters.elevation import ElevationAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRTM_PATH = PROJECT_ROOT / "data" / "dem" / "mumbai" / "srtm" / "srtm_mumbai.tif"


def test_srtm_file_exists() -> None:
    assert SRTM_PATH.exists()


def test_elevation_sampling() -> None:
    adapter = ElevationAdapter(SRTM_PATH)
    result = adapter.sample(latitude=19.076, longitude=72.8777)

    assert result.source == "SRTM"
    assert result.dataset == "srtm_mumbai.tif"
    assert isinstance(result.elevation_m, float)
    assert 0.0 <= result.elevation_risk <= 1.0
    assert result.resolution_x > 0
    assert result.resolution_y > 0


def test_lower_elevation_has_higher_risk() -> None:
    adapter = ElevationAdapter(SRTM_PATH)
    assert adapter._elevation_risk(10) > adapter._elevation_risk(90)


def test_risk_is_bounded() -> None:
    adapter = ElevationAdapter(SRTM_PATH)
    assert adapter._elevation_risk(-100) == 1.0
    assert adapter._elevation_risk(0) == 1.0
    assert adapter._elevation_risk(100) == 0.0
    assert adapter._elevation_risk(1000) == 0.0


def test_location_outside_raster_fails() -> None:
    adapter = ElevationAdapter(SRTM_PATH)
    with pytest.raises(ValueError):
        adapter.sample(latitude=25.0, longitude=80.0)
