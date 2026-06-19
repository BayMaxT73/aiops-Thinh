def is_worth_it(
    num_services: int,
    incidents_per_month: int,
    avg_incident_duration_hours: float,
    downtime_cost_per_hour: float,
    expected_mttr_reduction_pct: float = 0.4,
    aiops_monthly_cost: float = 15_000,
) -> dict:
    """
    Returns:
      {
        "monthly_value": float,
        "monthly_cost": float,
        "break_even_incidents_per_month": float,  # or float('inf')
        "roi": float,
        "payback_months": float,  # or float('inf')
        "verdict": "worth_it" | "marginal" | "not_worth_it"
      }
    Verdict rule:
      roi > 1.5 -> worth_it
      1.0 < roi <= 1.5 -> marginal
      roi <= 1.0 -> not_worth_it
    """
    if num_services < 0 or incidents_per_month < 0:
        raise ValueError("num_services and incidents_per_month must be non-negative")
    if avg_incident_duration_hours < 0 or downtime_cost_per_hour < 0:
        raise ValueError("duration and downtime cost must be non-negative")
    if expected_mttr_reduction_pct < 0:
        raise ValueError("expected_mttr_reduction_pct must be non-negative")
    if aiops_monthly_cost < 0:
        raise ValueError("aiops_monthly_cost must be non-negative")

    monthly_downtime_hours = incidents_per_month * avg_incident_duration_hours
    value_per_incident = (
        avg_incident_duration_hours
        * expected_mttr_reduction_pct
        * downtime_cost_per_hour
    )
    monthly_value = (
        monthly_downtime_hours
        * expected_mttr_reduction_pct
        * downtime_cost_per_hour
    )
    monthly_cost = aiops_monthly_cost
    roi = monthly_value / monthly_cost if monthly_cost else float("inf")
    payback_months = monthly_cost / monthly_value if monthly_value > 0 else float("inf")
    break_even_incidents_per_month = (
        monthly_cost / value_per_incident if value_per_incident > 0 else float("inf")
    )

    if roi > 1.5:
        verdict = "worth_it"
    elif roi > 1.0:
        verdict = "marginal"
    else:
        verdict = "not_worth_it"

    return {
        "monthly_value": monthly_value,
        "monthly_cost": monthly_cost,
        "break_even_incidents_per_month": break_even_incidents_per_month,
        "roi": roi,
        "payback_months": payback_months,
        "verdict": verdict,
    }


if __name__ == "__main__":
    print(is_worth_it(
        num_services=20,
        incidents_per_month=2,
        avg_incident_duration_hours=1,
        downtime_cost_per_hour=10_000,
        aiops_monthly_cost=15_000,
    ))
    print(is_worth_it(
        num_services=100,
        incidents_per_month=5,
        avg_incident_duration_hours=2,
        downtime_cost_per_hour=20_000,
        aiops_monthly_cost=25_000,
    ))
    # Example: internal B2B SaaS handling customer support workflows.
    # USD 8,000/hour is a defensible midpoint because prolonged downtime blocks agent productivity,
    # delays ticket handling, and creates contractual service-credit exposure without being fintech-scale.
    print(is_worth_it(
        num_services=40,
        incidents_per_month=3,
        avg_incident_duration_hours=0.75,
        downtime_cost_per_hour=8_000,
        expected_mttr_reduction_pct=0.35,
        aiops_monthly_cost=12_000,
    ))
