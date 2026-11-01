import pytest

from app.domain.schemas import LocationInput
from app.spatial.engine import SpatialEngine


@pytest.mark.asyncio
async def test_spatial_engine_preserves_location() -> None:
    result = await SpatialEngine().resolve(
        LocationInput(
            village="Test Village",
            district="Mumbai",
            state="Maharashtra",
            latitude=19.0760,
            longitude=72.8777,
        )
    )

    assert result.source == "local-placeholder"
    assert result.location.village == "Test Village"
    assert result.location.latitude == 19.0760
    assert result.map_data["type"] == "FeatureCollection"
