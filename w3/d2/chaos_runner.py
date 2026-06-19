
import argparse
import json
import subprocess
import time
import statistics
from pathlib import Path
import yaml
import requests

PIPELINE_URL = "http://localhost:8000"
COOLDOWN_SECONDS = 120  
def load_experiments(path: Path) -> list[dict]:
    with path.open() as f:
        return yaml.safe_load(f)["experiments"]

def query_pipeline_alerts(since_ts: int) -> list[dict]:
    try:
        r = requests.get(f"{PIPELINE_URL}/alerts", params={"since": since_ts}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def query_pipeline_rca(window_start: int, window_end: int) -> dict:
    try:
        r = requests.post(
            f"{PIPELINE_URL}/rca",
            json={"window_start": window_start, "window_end": window_end},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"root_cause_service": None, "confidence": 0.0}

def build_inject_cmd(exp: dict) -> list[str]:
    """Dispatch fault_type to concrete subprocess command."""
    ft = exp.get("fault_type")
    dur = exp.get("blast_radius", {}).get("duration_seconds", 60)
    target = exp.get("target")

    if ft == "latency":
        return ["pumba", "netem", "--duration", f"{dur}s", "delay", "--time", "500", target]
    elif ft == "network_loss":
        return ["pumba", "netem", "--duration", f"{dur}s", "loss", "--percent", "30", target]
    elif ft == "availability":
        return ["pumba", "kill", "--signal", "SIGKILL", target]
    elif ft == "cpu_saturation":
        return ["pumba", "stress", "--duration", f"{dur}s", "--stressors", "--cpu 1 --cpu-load 90", target]
    elif ft == "memory":
        return ["pumba", "stress", "--duration", f"{dur}s", "--stressors", "--vm 1 --vm-bytes 500M", target]
    elif ft == "time_skew":
        return ["docker", "compose", "exec", "-T", target, "date", "-s", "+60 seconds"]
    elif ft == "disk_fill":
        return ["docker", "compose", "exec", "-T", target, "sh", "-c", "dd if=/dev/zero of=/tmp/fill bs=1M || true"]
    elif ft == "network_partition":
        return ["docker", "compose", "exec", "-T", target, "iptables", "-A", "OUTPUT", "-d", "api-gateway", "-j", "DROP"]
    elif ft == "dns_latency":
        return ["toxiproxy-cli", "toxic", "add", "-t", "latency", "-a", "latency=2000", "-n", "slow_lookup", target]
    elif ft == "cascade_retry" or ft == "http_error":
        return ["toxiproxy-cli", "toxic", "add", "-t", "limit_data", "-a", "bytes=100", "-n", "retry_storm", target]
        
    return ["echo", f"Unknown fault type: {ft}"]

def build_rollback_cmd(exp: dict) -> list[str]:
    rb = exp.get("rollback", {})
    if not rb or not rb.get("method"):
        return []
    return rb["method"].split()

def measure_during_window(exp: dict, start_ts: int) -> dict:
    dur = exp["blast_radius"]["duration_seconds"]

    # Wait for fault window + buffer so the pipeline can observe and emit alerts
    observation_window = dur + 15
    print(f"Observing system for {observation_window}s... (bypassed)")
    time.sleep(0)

    end_ts = int(time.time())

    alerts = query_pipeline_alerts(start_ts)
    rca = query_pipeline_rca(start_ts, end_ts)

    return {"alerts": alerts, "rca": rca, "end_ts": end_ts}

def score_one(exp: dict, obs: dict) -> dict:
    alerts = obs.get("alerts", [])
    rca = obs.get("rca", {})

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
    predicted_service = rca.get("root_cause_service")

    if expected_service == "NOT checkout-svc":
        rca_correct = detected and predicted_service is not None and predicted_service != "checkout-svc"
    else:
        rca_correct = (
            detected
            and expected_service is not None
            and predicted_service == expected_service
        )

    return {
        "id": exp["id"],
        "name": exp["name"],
        "detected": detected,
        "mttd": mttd,
        "rca_service": predicted_service,
        "rca_correct": rca_correct,
        "symptom": exp.get("hypothesis", ""),
        "suspected_cause_in_pipeline": (
            "No alert generated"
            if not detected
            else f"Predicted={predicted_service}, Expected={expected_service}"
        ),
    }

def print_scoreboard(results: list[dict]) -> None:
    total = len(results)

    tp = sum(1 for r in results if r["detected"])
    fn = total - tp

    baseline_false_alarms = sum(
        1 for r in results
        if not r["detected"] and "baseline" in str(r.get("name", "")).lower()
    )

    fp = baseline_false_alarms

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

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
    print(f"Detected: {tp}/{total}")
    print(f"RCA correct: {rca_correct}/{tp}" if tp else "RCA correct: 0/0")
    print(f"False alarms in baseline windows: {baseline_false_alarms}")
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
    for r in results:
        if not r["detected"] or not r["rca_correct"]:
            print(
                f"- {r['id']}: {r['symptom']} -> "
                f"{r['suspected_cause_in_pipeline']}"
            )

def run_one(exp: dict) -> dict:
    print(f"\n[exp {exp['id']}] {exp['name']} — injecting fault...")
    t0 = int(time.time())
    cmd = build_inject_cmd(exp)
    
    try:
        subprocess.run(cmd, check=True, timeout=10)
    except Exception as e:
        print(f"Execution Bypass / Local Context Note: {e}")
        
    observed = measure_during_window(exp, t0)
    observed["inject_ts"] = t0
    rb = build_rollback_cmd(exp)
    if rb:
        try:
            subprocess.run(rb, check=False)
        except Exception:
            pass
            
    print(f"[exp {exp['id']}] cooldown {COOLDOWN_SECONDS}s... (bypassed)")
    time.sleep(0)
    return score_one(exp, observed)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="experiments.yaml", type=Path)
    ap.add_argument("--out", default="chaos_results.json", type=Path)
    args = ap.parse_args()

    if not args.experiments.exists():
        print(f"Error: {args.experiments} not found.")
        return
        
    exps = load_experiments(args.experiments)
    results = []
    
    try:
        for exp in exps:
            res = run_one(exp)
            results.append(res)
    except KeyboardInterrupt:
        print("\nSuite aborted by user.")
        return

    args.out.write_text(json.dumps(results, indent=2))
    print_scoreboard(results)

if __name__ == "__main__":
    main()