from app.risk.flood import FloodRiskEngine, FloodRiskInput


def test_flood_risk_low_when_all_indicators_are_low() -> None:
    result = FloodRiskEngine().calculate(
        FloodRiskInput(
            elevation_risk=0.1,
            rainfall_risk=0.1,
            flood_extent_risk=0.0,
            river_proximity_risk=0.1,
            historical_flood_risk=0.1,
        )
    )

    assert result.hazard_score == 0.075
    assert result.risk_score == 0.075
    assert result.risk_level == "low"
    assert result.contributing_factors == []


def test_flood_extent_contributes_to_risk_score() -> None:
    engine = FloodRiskEngine()

    without_extent = engine.calculate(
        FloodRiskInput(
            elevation_risk=0.0,
            rainfall_risk=0.0,
            flood_extent_risk=0.0,
            river_proximity_risk=0.0,
            historical_flood_risk=0.0,
        )
    )

    with_extent = engine.calculate(
        FloodRiskInput(
            elevation_risk=0.0,
            rainfall_risk=0.0,
            flood_extent_risk=1.0,
            river_proximity_risk=0.0,
            historical_flood_risk=0.0,
        )
    )

    assert without_extent.risk_score == 0.0
    assert with_extent.risk_score == 0.25
    assert with_extent.risk_score > without_extent.risk_score
    assert "flood_extent" in with_extent.contributing_factors
    assert with_extent.risk_level == "moderate"


def test_flood_risk_very_high_and_factors() -> None:
    result = FloodRiskEngine().calculate(
        FloodRiskInput(
            elevation_risk=0.9,
            rainfall_risk=0.9,
            flood_extent_risk=1.0,
            river_proximity_risk=0.8,
            historical_flood_risk=0.7,
            affected_area_sq_km=12.5,
        )
    )

    assert result.hazard_score == 0.88
    assert result.risk_level == "very_high"
    assert result.affected_area_sq_km == 12.5
    assert "rainfall" in result.contributing_factors
    assert "flood_extent" in result.contributing_factors
