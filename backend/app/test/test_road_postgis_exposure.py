from __future__ import annotations

import pytest

from app.spatial.adapters import road as road_module
from app.spatial.adapters.road import RoadPostGISExposureAdapter


class FakeCursor:
    def __init__(self):
        self.execute_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query):
        self.execute_count += 1

    def fetchone(self):
        return (4326, 4326)

    def fetchall(self):
        return [("primary", 100, 4), ("residential", 200, 6), ("service", 20, 0)]


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
    assert RoadPostGISExposureAdapter._normalize_database_url(
        "postgresql+psycopg2://user:pass@localhost/db"
    ) == "postgresql://user:pass@localhost/db"


def test_rejects_unsafe_table_identifier():
    with pytest.raises(ValueError, match="simple PostgreSQL identifier"):
        RoadPostGISExposureAdapter(
            "postgresql://user:pass@localhost/db",
            road_table="roads; DROP TABLE buildings",
        )


def test_calculates_road_exposure(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(
        road_module.psycopg2,
        "connect",
        lambda *args, **kwargs: connection,
    )
    result = RoadPostGISExposureAdapter(
        "postgresql://user:pass@localhost/db"
    ).calculate()

    assert result.roads_at_risk == 10
    assert result.total_road_features_in_analysis_area == 320
    assert result.affected_road_percentage == 3.125
    assert result.affected_by_class == {"primary": 4, "residential": 6}
    assert result.totals_by_class == {"primary": 100, "residential": 200, "service": 20}
    assert connection.fake_cursor.execute_count == 2
