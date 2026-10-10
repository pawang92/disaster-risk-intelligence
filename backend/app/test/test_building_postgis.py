import pytest

from app.spatial.adapters.building import BuildingPostGISExposureAdapter


def test_postgis_adapter_normalizes_sqlalchemy_url() -> None:
    adapter = BuildingPostGISExposureAdapter(
        "postgresql+psycopg://disaster:disaster@localhost:5432/disaster_risk"
    )
    assert adapter.database_url == (
        "postgresql://disaster:disaster@localhost:5432/disaster_risk"
    )


def test_postgis_adapter_rejects_invalid_table_name() -> None:
    with pytest.raises(ValueError, match="simple PostgreSQL identifier"):
        BuildingPostGISExposureAdapter(
            "postgresql://disaster:disaster@localhost:5432/disaster_risk",
            building_table="buildings;drop table",
        )


def test_postgis_adapter_requires_database_url() -> None:
    with pytest.raises(ValueError, match="database_url is required"):
        BuildingPostGISExposureAdapter("   ")

def test_orchestrator_wires_postgis_building_adapter_by_default(monkeypatch) -> None:
    from app.core.config import Settings
    from app.services import risk_orchestrator as orchestrator_module

    class FakePostGISAdapter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_adapter(*args, **kwargs):
        return object()

    for name in (
        "SpatialEngine",
        "FloodRiskEngine",
        "ElevationAdapter",
        "RainfallAdapter",
        "FloodExtentAdapter",
        "RiverProximityAdapter",
        "HistoricalFloodAdapter",
        "PopulationExposureAdapter",
    ):
        monkeypatch.setattr(orchestrator_module, name, fake_adapter)

    monkeypatch.setattr(
        orchestrator_module,
        "BuildingPostGISExposureAdapter",
        FakePostGISAdapter,
    )

    settings = Settings(
        postgis_url="postgresql://test:test@localhost:5432/test",
        building_exposure_backend="postgis",
    )
    orchestrator = orchestrator_module.RiskOrchestrator(settings)

    assert isinstance(
        orchestrator.building_exposure_adapter,
        FakePostGISAdapter,
    )
    assert orchestrator.building_exposure_adapter.kwargs == {
        "database_url": "postgresql://test:test@localhost:5432/test",
        "building_table": "mumbai_building_footprints",
        "flood_table": "mumbai_s1_flood_extent",
    }

