from app.spatial.adapters.building import (
    BuildingExposureAdapter,
    BuildingExposureResult,
    BuildingPostGISExposureAdapter,
)
from app.spatial.adapters.elevation import ElevationAdapter, ElevationResult
from app.spatial.adapters.flood_extent import FloodExtentAdapter, FloodExtentResult
from app.spatial.adapters.historical_flood import (
    HistoricalFloodAdapter,
    HistoricalFloodResult,
)
from app.spatial.adapters.population import (
    PopulationExposureAdapter,
    PopulationExposureResult,
)
from app.spatial.adapters.rainfall import RainfallAdapter, RainfallResult
from app.spatial.adapters.river_proximity import (
    RiverProximityAdapter,
    RiverProximityResult,
)

__all__ = [
    "BuildingExposureAdapter",
    "BuildingExposureResult",
    "BuildingPostGISExposureAdapter",
    "ElevationAdapter",
    "ElevationResult",
    "FloodExtentAdapter",
    "FloodExtentResult",
    "HistoricalFloodAdapter",
    "HistoricalFloodResult",
    "PopulationExposureAdapter",
    "PopulationExposureResult",
    "RainfallAdapter",
    "RainfallResult",
    "RiverProximityAdapter",
    "RiverProximityResult",
]
