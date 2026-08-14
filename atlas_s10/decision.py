"""Operational policy translating a distribution into procurement quantities."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProcurementScenario:
    current_stock_liters: float = 18_000
    tank_capacity_liters: float = 100_000
    daily_consumption_liters: float = 2_500
    planning_horizon_days: int = 30
    safety_stock_days: float = 5
    supplier_lead_days: float = 3
    risk_tolerance: str = "moderate"


def recommend(forecast: dict, scenario: ProcurementScenario) -> dict:
    if min(
        scenario.current_stock_liters,
        scenario.tank_capacity_liters,
        scenario.daily_consumption_liters,
    ) < 0:
        raise ValueError("Volumes e consumo não podem ser negativos")
    if scenario.current_stock_liters > scenario.tank_capacity_liters:
        raise ValueError("Estoque atual excede a capacidade do tanque")
    if scenario.risk_tolerance not in {"conservative", "moderate", "aggressive"}:
        raise ValueError("risk_tolerance deve ser conservative, moderate ou aggressive")

    demand = scenario.daily_consumption_liters * scenario.planning_horizon_days
    safety = scenario.daily_consumption_liters * scenario.safety_stock_days
    required = max(0.0, demand + safety - scenario.current_stock_liters)
    capacity_available = max(0.0, scenario.tank_capacity_liters - scenario.current_stock_liters)
    feasible_need = min(required, capacity_available)
    coverage_days = (
        scenario.current_stock_liters / scenario.daily_consumption_liters
        if scenario.daily_consumption_liters
        else float("inf")
    )
    forced_shortage = max(
        0.0,
        scenario.daily_consumption_liters
        * (scenario.supplier_lead_days + scenario.safety_stock_days)
        - scenario.current_stock_liters,
    )

    probability_up = float(forecast["probability_relevant_up"])
    expected_change = float(forecast["change_pct"])
    tolerance_multiplier = {"conservative": 1.15, "moderate": 1.0, "aggressive": 0.8}[
        scenario.risk_tolerance
    ]
    score = probability_up * max(expected_change, 0.0) * tolerance_multiplier
    if forced_shortage > 0:
        fraction = max(0.45, min(1.0, forced_shortage / max(feasible_need, 1.0)))
        signal = "COBERTURA CRÍTICA"
        action = "REPOR ESTOQUE E ANTECIPAR PARCIALMENTE"
        rationale = "A cobertura de estoque é menor que lead time + segurança."
    elif probability_up >= 0.72 and expected_change >= 0.30:
        fraction = 0.70 if scenario.risk_tolerance == "conservative" else 0.60
        signal = "RISCO DE ALTA"
        action = "ANTECIPAR PARCIALMENTE"
        rationale = "A distribuição indica alta relevante, preservando flexibilidade para o saldo."
    elif probability_up >= 0.56 and expected_change > 0:
        fraction = 0.40
        signal = "PRESSÃO DE ALTA"
        action = "COMPRAR PARCIALMENTE"
        rationale = "O risco está inclinado para cima, mas a convicção não justifica compra integral."
    elif probability_up <= 0.38 and coverage_days > scenario.supplier_lead_days + scenario.safety_stock_days:
        fraction = 0.0
        signal = "VIÉS DE QUEDA"
        action = "AGUARDAR"
        rationale = "Há cobertura operacional e a distribuição favorece postergação."
    else:
        fraction = 0.25
        signal = "NEUTRO"
        action = "MANTER COMPRA TÁTICA"
        rationale = "A incerteza recomenda uma posição pequena e reversível."

    purchase_now = min(capacity_available, max(forced_shortage, feasible_need * fraction))
    purchase_now = max(0.0, round(purchase_now / 500) * 500)
    purchase_later = max(0.0, feasible_need - purchase_now)
    expected_unit_saving = max(0.0, float(forecast["point"]) - float(forecast["current_price"]))
    expected_saving = purchase_now * expected_unit_saving
    downside_unit = max(0.0, float(forecast["current_price"]) - float(forecast["p10"]))
    timing_risk = purchase_now * downside_unit

    return {
        "signal": signal,
        "action": action,
        "rationale": rationale,
        "purchase_now_liters": purchase_now,
        "purchase_later_liters": purchase_later,
        "required_liters": feasible_need,
        "demand_liters": demand,
        "stock_coverage_days": coverage_days,
        "capacity_available_liters": capacity_available,
        "expected_savings_brl": expected_saving,
        "timing_risk_brl": timing_risk,
        "policy_score": score,
        "assumptions": asdict(scenario),
        "disclaimer": "Suporte à decisão sob as premissas informadas; não é uma ordem absoluta de compra.",
    }

