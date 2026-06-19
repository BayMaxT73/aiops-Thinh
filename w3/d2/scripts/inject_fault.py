#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
FAULT_DIR = RUNTIME / "faults"
ALERT_HISTORY = RUNTIME / "alert_history.jsonl"
FAULT_HISTORY = RUNTIME / "fault_history.jsonl"
COMPOSE_FILE = ROOT / "docker-compose.yml"
TIME_SCALE = float(os.environ.get("CHAOS_TIME_SCALE", "0.1"))

ALERT_MAP = {
    "latency": ("HighLatency", "warning", 3),
    "network_loss": ("HighErrorRate", "critical", 3),
    "availability": ("InstanceDown", "critical", 5),
    "cpu_saturation": ("CpuSaturation", "warning", 4),
    "memory": ("DbMemoryPressure", "critical", 4),
    "disk_fill": ("LogIngestionLag", "warning", 4),
    "time_skew": ("AuthTimeSkew", "critical", 3),
    "network_partition": ("EdgePartition", "critical", 2),
    "dns_latency": ("DnsSlow", "warning", 4),
    "http_error": ("HighErrorRate", "critical", 3),
}


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def write_fault(fault: dict) -> None:
    FAULT_DIR.mkdir(parents=True, exist_ok=True)
    (FAULT_DIR / f'{fault["target"]}.json').write_text(json.dumps(fault), encoding="utf-8")


def clear_fault(target: str) -> None:
    path = FAULT_DIR / f"{target}.json"
    if path.exists():
        path.unlink()


def docker_compose(*args: str) -> None:
    subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fault-type", help="fault type to inject")
    ap.add_argument("--target", required=True, help="target service")
    ap.add_argument("--duration", type=int, default=60, help="logical duration in seconds")
    ap.add_argument("--clear", action="store_true", help="clear active fault without waiting")
    args = ap.parse_args()

    if args.clear:
        clear_fault(args.target)
        return

    now = int(time.time())
    scaled_duration = max(2, int(args.duration * TIME_SCALE))
    scaled_alert_delay = max(1, int(ALERT_MAP[args.fault_type][2] * TIME_SCALE))

    fault = {
        "fault_type": args.fault_type,
        "target": args.target,
        "start_ts": now,
        "end_ts": now + scaled_duration,
        "logical_duration_seconds": args.duration,
        "scaled_duration_seconds": scaled_duration,
    }

    alertname, severity, _ = ALERT_MAP[args.fault_type]
    append_jsonl(FAULT_HISTORY, fault)
    append_jsonl(
        ALERT_HISTORY,
        {
            "alertname": alertname,
            "service": args.target,
            "severity": severity,
            "fire_ts": now + scaled_alert_delay,
            "timestamp": now + scaled_alert_delay,
            "fault_type": args.fault_type,
        },
    )

    write_fault(fault)
    try:
        time.sleep(scaled_duration)
    finally:
        clear_fault(args.target)


if __name__ == "__main__":
    main()
