# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "tabulate",
# ]
# ///

from tabulate import tabulate

tiers = {
    "Small": {"services": 10, "log_gb_day": 50, "metric_eps": 100_000},
    "Medium": {"services": 100, "log_gb_day": 500, "metric_eps": 1_000_000},
    "Large": {"services": 1000, "log_gb_day": 5000, "metric_eps": 10_000_000},
}

DAYS_PER_MONTH = 30

def calculate_build_cost(tier_data):
    logs_gb_month = tier_data["log_gb_day"] * DAYS_PER_MONTH
    storage_cost = logs_gb_month * 0.10
    
    if tier_data["services"] <= 10:
        compute_cost = 600
    elif tier_data["services"] <= 100:
        compute_cost = 4500
    else:
        compute_cost = 35000
        
    network_cost = logs_gb_month * 0.02 + (tier_data["metric_eps"] / 1000) * 5
    
    total = storage_cost + compute_cost + network_cost
    return {
        "Storage": storage_cost,
        "Compute": compute_cost,
        "Network": network_cost,
        "Total": total
    }

def calculate_buy_cost(tier_data):
    apm_cost = tier_data["services"] * 31
    logs_gb_month = tier_data["log_gb_day"] * DAYS_PER_MONTH
    logs_cost = logs_gb_month * 2.50
    metrics_cost = (tier_data["metric_eps"] / 1000) * 150 
    
    total = apm_cost + logs_cost + metrics_cost
    return {
        "APM/Infra": apm_cost,
        "Logs": logs_cost,
        "Metrics": metrics_cost,
        "Total": total
    }

print("=== COST ESTIMATION: BUILD (Self-Host) vs BUY (Datadog SaaS) ===\n")

build_table = []
buy_table = []
comparison_table = []

for tier, data in tiers.items():
    build = calculate_build_cost(data)
    build_table.append([tier, f"${build['Storage']:,.2f}", f"${build['Compute']:,.2f}", f"${build['Network']:,.2f}", f"${build['Total']:,.2f}"])
    
    buy = calculate_buy_cost(data)
    buy_table.append([tier, f"${buy['APM/Infra']:,.2f}", f"${buy['Logs']:,.2f}", f"${buy['Metrics']:,.2f}", f"${buy['Total']:,.2f}"])
    
    comparison_table.append([tier, f"${build['Total']:,.2f}", f"${buy['Total']:,.2f}", f"${buy['Total'] - build['Total']:,.2f}"])

print("--- BUILD (Self-Host: OTel, Kafka, Flink, ES) ---")
print(tabulate(build_table, headers=["Tier", "Storage", "Compute", "Network", "Total Build Cost"], tablefmt="github"))
print("\n--- BUY (Datadog SaaS) ---")
print(tabulate(buy_table, headers=["Tier", "APM/Services", "Logs Cost", "Metrics Cost", "Total Buy Cost"], tablefmt="github"))
print("\n--- COMPARISON (Build vs Buy) ---")
print(tabulate(comparison_table, headers=["Tier", "Build Cost", "Buy (SaaS) Cost", "SaaS Premium (Buy - Build)"], tablefmt="github"))
