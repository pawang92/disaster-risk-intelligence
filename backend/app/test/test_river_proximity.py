from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from app.spatial.adapters.river_proximity import RiverProximityAdapter


def _create_river_dataset(path: Path) -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["Test River"]},
        geometry=[LineString([(72.87, 19.07), (72.87, 19.08)])],
        crs="EPSG:4326",
    )
    gdf.to_file(path, driver="GeoJSON")


def test_river_proximity_near_river(tmp_path: Path) -> None:
    path = tmp_path / "rivers.geojson"
    _create_river_dataset(path)

    adapter = RiverProximityAdapter(
        path,
        near_distance_m=500.0,
        far_distance_m=5000.0,
    )

    result = adapter.sample(latitude=19.075, longitude=72.87)

    assert result.distance_to_river_m >= 0.0
    assert result.river_proximity_risk == 1.0
    assert result.source == "local_river_vector"


def test_river_proximity_far_from_river(tmp_path: Path) -> None:
    path = tmp_path / "rivers.geojson"
    _create_river_dataset(path)

    adapter = RiverProximityAdapter(
        path,
        near_distance_m=500.0,
        far_distance_m=5000.0,
    )

    result = adapter.sample(latitude=19.15, longitude=72.95)

    assert result.distance_to_river_m > 5000.0
    assert result.river_proximity_risk == 0.0


def test_river_proximity_interpolates_risk(tmp_path: Path) -> None:
    path = tmp_path / "rivers.geojson"
    _create_river_dataset(path)

    adapter = RiverProximityAdapter(
        path,
        near_distance_m=100.0,
        far_distance_m=1000.0,
    )

    result = adapter.sample(latitude=19.075, longitude=72.88)

    assert 0.0 < result.river_proximity_risk < 1.0


def test_river_dataset_requires_crs(tmp_path: Path) -> None:
    path = tmp_path / "rivers.geojson"
    gdf = gpd.GeoDataFrame(
        {"name": ["Test River"]},
        geometry=[LineString([(72.87, 19.07), (72.87, 19.08)])],
    )
    gdf.to_file(path, driver="GeoJSON")

    try:
        RiverProximityAdapter(path)
    except ValueError as exc:
        assert "CRS" in str(exc)
    else:
        raise AssertionError("Expected missing CRS to raise ValueError")
