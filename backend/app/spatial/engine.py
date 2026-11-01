from __future__ import annotations

from dataclasses import dataclass

from app.domain.schemas import LocationInput
from app.spatial.models import SpatialLocation, SpatialResult


@dataclass(slots=True)
class SpatialEngine:
    """Resolve and enrich a disaster-analysis location.

    This interface deliberately has no database dependency. A PostGIS adapter
    will implement the same contract when spatial datasets are connected.
    """

    async def resolve(self, location: LocationInput) -> SpatialResult:
        return SpatialResult(
            location=SpatialLocation(
                latitude=location.latitude,
                longitude=location.longitude,
                village=location.village,
                district=location.district,
                state=location.state,
            ),
            source="local-placeholder",
        )
