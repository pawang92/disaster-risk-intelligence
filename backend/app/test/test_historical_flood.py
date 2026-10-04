from pathlib import Path

import pytest

from app.spatial.adapters.historical_flood import HistoricalFloodAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_ROOT = PROJECT_ROOT / "data" / "historical_flood"

FREQUENCY_PATH = (
    DATA_ROOT / "mumbai_historical_flood_frequency.tif"
)

PRESENCE_PATH = (
    DATA_ROOT / "mumbai_historical_flood_presence.tif"
)

DURATION_PATH = (
    DATA_ROOT / "mumbai_maximum_historical_flood_duration.tif"
)

EXTENT_PATH = (
    DATA_ROOT / "mumbai_maximum_historical_flood_extent.tif"
)


def create_adapter() -> HistoricalFloodAdapter:
    return HistoricalFloodAdapter(
        frequency_path=FREQUENCY_PATH,
        presence_path=PRESENCE_PATH,
        duration_path=DURATION_PATH,
        extent_path=EXTENT_PATH,
    )


def test_historical_flood_adapter_initializes() -> None:
    adapter = create_adapter()

    assert adapter.frequency_path.exists()
    assert adapter.presence_path.exists()
    assert adapter.duration_path.exists()
    assert adapter.extent_path.exists()


def test_historical_flood_sample() -> None:
    adapter = create_adapter()

    result = adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    assert 0.0 <= result.frequency_risk <= 1.0
    assert 0.0 <= result.presence_risk <= 1.0
    assert 0.0 <= result.duration_risk <= 1.0
    assert 0.0 <= result.extent_risk <= 1.0
    assert 0.0 <= result.historical_flood_risk <= 1.0

    assert result.source == "local_historical_flood_rasters"

    assert (
        result.frequency_dataset
        == "mumbai_historical_flood_frequency.tif"
    )

    assert (
        result.presence_dataset
        == "mumbai_historical_flood_presence.tif"
    )

    assert (
        result.duration_dataset
        == "mumbai_maximum_historical_flood_duration.tif"
    )

    assert (
        result.extent_dataset
        == "mumbai_maximum_historical_flood_extent.tif"
    )


def test_historical_flood_score_calculation() -> None:
    adapter = create_adapter()

    result = adapter.sample(
        latitude=19.076,
        longitude=72.8777,
    )

    expected = round(
        (
            result.frequency_risk * 0.25
            + result.presence_risk * 0.25
            + result.duration_risk * 0.25
            + result.extent_risk * 0.25
        ),
        4,
    )

    assert result.historical_flood_risk == expected


def test_historical_flood_location_outside_bounds() -> None:
    adapter = create_adapter()

    with pytest.raises(ValueError, match="outside"):
        adapter.sample(
            latitude=20.0,
            longitude=75.0,
        )


def test_missing_historical_flood_dataset(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        HistoricalFloodAdapter(
            frequency_path=tmp_path / "frequency.tif",
            presence_path=PRESENCE_PATH,
            duration_path=DURATION_PATH,
            extent_path=EXTENT_PATH,
        )