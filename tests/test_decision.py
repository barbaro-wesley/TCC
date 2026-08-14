import pytest

from atlas_s10.decision import ProcurementScenario, recommend

FORECAST = {
    "probability_relevant_up": 0.8,
    "change_pct": 1.0,
    "point": 7.2,
    "current_price": 7.0,
    "p10": 6.8,
}


def test_recommendation_respects_capacity_and_nonnegative_quantities():
    scenario = ProcurementScenario(current_stock_liters=90_000, tank_capacity_liters=100_000)
    result = recommend(FORECAST, scenario)
    assert 0 <= result["purchase_now_liters"] <= 10_000
    assert result["purchase_later_liters"] >= 0


def test_invalid_tank_state_is_rejected():
    scenario = ProcurementScenario(current_stock_liters=110_000, tank_capacity_liters=100_000)
    with pytest.raises(ValueError, match="excede"):
        recommend(FORECAST, scenario)

