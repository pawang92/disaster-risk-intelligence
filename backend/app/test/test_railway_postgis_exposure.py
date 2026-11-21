from __future__ import annotations

import pytest

from app.spatial.adapters import railway as railway_module
from app.spatial.adapters.railway import RailwayPostGISExposureAdapter


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
        return [
            ("rail", 100, 2),
            ("subway", 20, 1),
            ("monorail", 5, 0),
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
    assert (
        RailwayPostGISExposureAdapter._normalize_database_url(
            "postgresql+psycopg://user:pass@localhost/db"
        )
        == "postgresql://user:pass@localhost/db"
    )


def test_rejects_unsafe_table_identifier():
    with pytest.raises(ValueError, match="simple PostgreSQL identifier"):
        RailwayPostGISExposureAdapter(
            "postgresql://user:pass@localhost/db",
            railway_table="railway; DROP TABLE buildings",
        )


def test_calculates_railway_exposure(monkeypatch):
    fake_connection = FakeConnection()
    monkeypatch.setattr(
        railway_module.psycopg2,
        "connect",
        lambda *args, **kwargs: fake_connection,
    )
    adapter = RailwayPostGISExposureAdapter(
        "postgresql://user:pass@localhost/db"
    )

    result = adapter.calculate()

    assert result.railways_at_risk == 3
    assert result.total_railway_features_in_analysis_area == 125
    assert result.affected_railway_percentage == 2.4
    assert result.affected_by_class == {"rail": 2, "subway": 1}
    assert result.railway_dataset == "mumbai_suburban_railway"
    assert result.flood_dataset == "mumbai_s1_flood_extent"
    assert fake_connection.fake_cursor.execute_count == 2
