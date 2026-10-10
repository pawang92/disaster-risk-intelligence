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
