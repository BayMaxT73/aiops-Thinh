#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone
import requests

PIPELINE_URL = "http://localhost:8000"
ROOT = Path(__file__).resolve().parents[1]
EVENTS_FILE = ROOT / "runtime" / "events.jsonl"

def docker_events_tail(duration: int) -> list[dict]:
    try:
        out = subprocess.run(
            ["docker", "events", "--since", f"{duration}s", "--until", "0s", "--format", "{{.Time}}\t{{.Type}}\t{{.Status}}\t{{.Actor.Attributes.name}}"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except Exception:
        return []
    events = []
    for line in out.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        ts_epoch = int(parts[0])
        events.append({
            "ts": datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat(timespec="seconds"),
            "source": "docker",
            "event": f"{parts[2]} {parts[3]}"
        })
    return events

def pipeline_alerts(since: int) -> list[dict]:
    try:
        r = requests.get(f"{PIPELINE_URL}/alerts", params={"since": since}, timeout=3)
        r.raise_for_status()
    except Exception:
        return []
    events = []
    for a in r.json():
        events.append({
            "ts": datetime.fromtimestamp(a.get("fire_ts", 0), tz=timezone.utc).isoformat(timespec="seconds"),
            "source": "pipeline",
            "event": f"pipeline-alert={a.get('alertname') or a.get('name')} svc={a.get('service')}"
        })
    return events

def internal_events() -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    rows = []
    for line in EVENTS_FILE.read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=20)
    ap.add_argument("--out", default="timeline.json", type=Path)
    args = ap.parse_args()
    start_ts = int(time.time())
    time.sleep(args.duration)
    events = docker_events_tail(args.duration) + pipeline_alerts(start_ts) + internal_events()
    events.sort(key=lambda e: e["ts"])
    args.out.write_text(json.dumps(events, indent=2), encoding='utf-8')
    print(f"Wrote {args.out} with {len(events)} events")

if __name__ == '__main__':
    main()
