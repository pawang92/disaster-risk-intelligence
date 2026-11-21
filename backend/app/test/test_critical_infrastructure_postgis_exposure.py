from __future__ import annotations

import pytest

from app.spatial.adapters import critical_infrastructure as critical_module
from app.spatial.adapters.critical_infrastructure import (
    CriticalInfrastructurePostGISExposureAdapter,
)


class FakeCursor:
    def __init__(self):
        self.execute_count = 0
        self.query_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        self.execute_count += 1
        self.query_params = params

    def fetchone(self):
        return (4326, 4326)

    def fetchall(self):
        return [
            ("hospital", 10, 2),
            ("pharmacy", 5, 1),
            ("school", 20, 0),
        ]


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.fake_cursor


def test_normalizes_sqlalchemy_postgres_url():
    assert CriticalInfrastructurePostGISExposureAdapter._normalize_database_url(
        "postgresql+psycopg://user:pass@localhost/db"
    ) == "postgresql://user:pass@localhost/db"


def test_rejects_unsafe_table_identifier():
    with pytest.raises(ValueError, match="simple PostgreSQL identifier"):
        CriticalInfrastructurePostGISExposureAdapter(
            "postgresql://user:pass@localhost/db",
            poi_table="poi; DROP TABLE buildings",
        )


def test_calculates_critical_asset_exposure(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(
        critical_module.psycopg2,
        "connect",
        lambda *args, **kwargs: connection,
    )
    adapter = CriticalInfrastructurePostGISExposureAdapter(
        "postgresql://user:pass@localhost/db"
    )

    result = adapter.calculate()

    assert result.critical_assets_at_risk == 3
    assert result.total_critical_assets_in_analysis_area == 35
    assert result.affected_critical_asset_percentage == 8.5714
    assert result.affected_by_category == {"hospital": 2, "pharmacy": 1}
    assert result.totals_by_category == {"hospital": 10, "pharmacy": 5, "school": 20}
    assert result.affected_percentage_by_category == {
        "hospital": 20.0,
        "pharmacy": 20.0,
        "school": 0.0,
    }
    assert connection.fake_cursor.query_params == (list(adapter.categories),)
    assert connection.fake_cursor.execute_count == 2


def test_rejects_empty_category_list():
    with pytest.raises(ValueError, match="At least one critical POI category"):
        CriticalInfrastructurePostGISExposureAdapter(
            "postgresql://user:pass@localhost/db",
            categories=[],
        )
