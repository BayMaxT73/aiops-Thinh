import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

PIPELINE_URL = "http://localhost:8000"
COOLDOWN_SECONDS = 5
DEFAULT_TOPOLOGY_PATH = Path("configs/service_topology.yaml")
INJECT_SCRIPT_PATH = Path("scripts/inject_fault.py")


def load_experiments(path: Path) -> list[dict]:
    with path.open() as f:
        return yaml.safe_load(f)["experiments"]


def load_topology(path: Path) -> dict:
    if not path.exists():
        return {"services": {}}
    with path.open() as f:
        return yaml.safe_load(f) or {"services": {}}


def query_pipeline_alerts(since_ts: int) -> list[dict]:
    r = requests.get(f"{PIPELINE_URL}/alerts", params={"since": since_ts}, timeout=10)
    r.raise_for_status()
    return r.json()


def query_pipeline_rca(window_start: int, window_end: int) -> dict:
    r = requests.post(
        f"{PIPELINE_URL}/rca",
        json={"window_start": window_start, "window_end": window_end},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def rca_root_service(rca: dict) -> str | None:
    if not isinstance(rca, dict):
        return None
    return rca.get("root_cause_service") or rca.get("root_service")


def has_dependency(topology: dict, source: str, target: str) -> bool:
    services = topology.get("services", {})
    if source not in services or target not in services:
        return False

    stack = list(services[source].get("depends_on", []))
    seen = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(services.get(node, {}).get("depends_on", []))
    return False


def normalize_rca_root(exp: dict, rca: dict, topology: dict) -> tuple[str | None, str | None]:
    predicted = rca_root_service(rca)
    target = exp.get("target")
    services = topology.get("services", {})

    if not predicted or not target or predicted == target:
        return predicted, None

    if services.get(target, {}).get("kind") != "infrastructure":
        return predicted, None

    if has_dependency(topology, predicted, target):
        return target, f"{predicted} depends on infrastructure target {target}"

    return predicted, None


def build_inject_cmd(exp: dict) -> list[str]:
    return [
        sys.executable,
        str(INJECT_SCRIPT_PATH),
        "--fault-type",
        str(exp.get("fault_type")),
        "--target",
        str(exp.get("target")),
        "--duration",
        str(exp.get("blast_radius", {}).get("duration_seconds", 60)),
    ]


def build_rollback_cmd(exp: dict) -> list[str]:
    return [sys.executable, str(INJECT_SCRIPT_PATH), "--clear", "--target", str(exp.get("target"))]


def measure_during_window(start_ts: int) -> dict:
    end_ts = int(time.time())
    alerts = query_pipeline_alerts(start_ts)
    rca = query_pipeline_rca(start_ts, end_ts)
    return {"alerts": alerts, "rca": rca, "end_ts": end_ts}


def score_one(exp: dict, obs: dict) -> dict:
    alerts = obs.get("alerts", [])
    rca = obs.get("rca", {})
    predicted_service, mapping_reason = normalize_rca_root(exp, rca, obs.get("topology", {}))

    detected = len(alerts) > 0
    mttd = None
    if detected:
        timestamps = [
            a.get("timestamp")
            for a in alerts
            if isinstance(a.get("timestamp"), (int, float))
        ]
        if timestamps:
            first_alert_ts = min(timestamps)
            inject_ts = obs.get("inject_ts", first_alert_ts)
            mttd = max(0, first_alert_ts - inject_ts)

    expected_service = exp.get("ground_truth", {}).get("expected_root_service")
    if expected_service == "NOT checkout-svc":
        rca_correct = detected and predicted_service is not None and predicted_service != "checkout-svc"
    else:
        rca_correct = detected and expected_service is not None and predicted_service == expected_service

    return {
        "id": exp["id"],
        "name": exp["name"],
        "detected": detected,
        "mttd": mttd,
        "rca_service": predicted_service,
        "raw_rca_service": rca_root_service(rca),
        "rca_correct": rca_correct,
        "mapping_applied": mapping_reason is not None,
        "mapping_reason": mapping_reason,
        "symptom": exp.get("hypothesis", ""),
        "suspected_cause_in_pipeline": (
            "No alert generated"
            if not detected
            else f"Predicted={predicted_service}, Expected={expected_service}"
        ),
    }


def print_scoreboard(results: list[dict]) -> None:
    total = len(results)
    detected = sum(1 for r in results if r["detected"])
    false_alarms = sum(
        1 for r in results
        if not r["detected"] and "baseline" in str(r.get("name", "")).lower()
    )
    precision = detected / (detected + false_alarms) if (detected + false_alarms) else 0.0
    recall = detected / total if total else 0.0
    rca_correct = sum(1 for r in results if r["rca_correct"])

    mttds = [r["mttd"] for r in results if r["mttd"] is not None]
    if mttds:
        mttds.sort()
        p50 = mttds[len(mttds) // 2]
        p95 = mttds[min(len(mttds) - 1, int(len(mttds) * 0.95))]
        mttd_line = f"MTTD p50: {p50:.1f}s, p95: {p95:.1f}s"
    else:
        mttd_line = "MTTD p50: n/a, p95: n/a"

    print("==== Chaos Run ====")
    print(f"Total: {total}")
    print(f"Detected: {detected}/{total}")
    print(f"RCA correct: {rca_correct}/{detected}" if detected else "RCA correct: 0/0")
    print(f"False alarms in baseline windows: {false_alarms}")
    print(f"Precision: {precision:.2f}")
    print(f"Recall: {recall:.2f}")
    print(mttd_line)

    print("\nPer-experiment:")
    print("| # | name              | detected | mttd  | rca_service  | rca_correct |")
    print("|---|-------------------|----------|-------|--------------|-------------|")
    for r in results:
        print(
            f"| {r['id']} | {r['name']} | "
            f"{'Y' if r['detected'] else 'N'} | "
            f"{str(int(r['mttd'])) + 's' if r['mttd'] is not None else 'n/a'} | "
            f"{r['rca_service'] or '-'} | "
            f"{'Y' if r['rca_correct'] else 'N'} |"
        )

    print("\nGaps identified:")
    gaps = [r for r in results if not r["detected"] or not r["rca_correct"]]
    if not gaps:
        print("- none")
        return
    for r in gaps:
        print(f"- {r['id']}: {r['symptom']} -> {r['suspected_cause_in_pipeline']}")


def run_one(exp: dict, topology: dict) -> dict:
    print(f"\n[exp {exp['id']}] {exp['name']} - injecting fault...")
    t0 = int(time.time())
    subprocess.run(build_inject_cmd(exp), check=True, timeout=180)

    observed = measure_during_window(t0)
    observed["inject_ts"] = t0
    observed["topology"] = topology

    subprocess.run(build_rollback_cmd(exp), check=False)
    print(f"[exp {exp['id']}] cooldown {COOLDOWN_SECONDS}s...")
    time.sleep(COOLDOWN_SECONDS)
    return score_one(exp, observed)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="experiments.yaml", type=Path)
    ap.add_argument("--out", default="chaos_results.json", type=Path)
    ap.add_argument("--topology", default=DEFAULT_TOPOLOGY_PATH, type=Path)
    args = ap.parse_args()

    experiments = load_experiments(args.experiments)
    topology = load_topology(args.topology)
    results = [run_one(exp, topology) for exp in experiments]

    args.out.write_text(json.dumps(results, indent=2))
    print_scoreboard(results)


if __name__ == "__main__":
    main()
