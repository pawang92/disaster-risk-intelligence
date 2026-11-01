from pathlib import Path
import pytest
from app.spatial.adapters.rainfall import RainfallAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[3]

TOTAL_RAINFALL_PATH = (
    PROJECT_ROOT
    / "data"
    / "rainfall"
    / "mumbai_imerg_total_rainfall_jul_aug_2024.tif"
)

MAX_DAILY_RAINFALL_PATH = (
    PROJECT_ROOT
    / "data"
    / "rainfall"
    / "mumbai_imerg_max_daily_rainfall_jul_aug_2024.tif"
)


@pytest.fixture
def rainfall_adapter() -> RainfallAdapter:
    return RainfallAdapter(
        total_rainfall_path=TOTAL_RAINFALL_PATH,
        max_daily_rainfall_path=MAX_DAILY_RAINFALL_PATH,
    )


def test_rainfall_files_exist() -> None:
    assert TOTAL_RAINFALL_PATH.exists()
    assert MAX_DAILY_RAINFALL_PATH.exists()


def test_rainfall_sample_returns_valid_values(
    rainfall_adapter: RainfallAdapter,
) -> None:
    result = rainfall_adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    assert result.latitude == 19.076
    assert result.longitude == 72.8777

    assert result.total_rainfall_mm >= 0.0
    assert result.max_daily_rainfall_mm >= 0.0

    assert 0.0 <= result.rainfall_risk <= 1.0

    assert result.source == "NASA GPM IMERG"

    assert (
        result.period
        == "2024-07-01/2024-08-31"
    )

def test_rainfall_dataset_names(
    rainfall_adapter: RainfallAdapter,
) -> None:
    result = rainfall_adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    assert (
        result.total_dataset
        == "mumbai_imerg_total_rainfall_jul_aug_2024.tif"
    )

    assert (
        result.max_daily_dataset
        == "mumbai_imerg_max_daily_rainfall_jul_aug_2024.tif"
    )


def test_rainfall_location_outside_raster(
    rainfall_adapter: RainfallAdapter,
) -> None:
    with pytest.raises(ValueError):
        rainfall_adapter.sample(
            latitude=28.6139,
            longitude=77.2090,
        )