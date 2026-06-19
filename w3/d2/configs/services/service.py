import json
import os
import random
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SERVICE = os.environ.get("SERVICE_NAME", "unknown")
PORT = int(os.environ.get("SERVICE_PORT", "8080"))
BASE_LAT_MS = float(os.environ.get("BASE_LATENCY_MS", "50"))
JITTER_MS = float(os.environ.get("JITTER_MS", "10"))
FAIL_RATE = float(os.environ.get("FAIL_RATE", "0.01"))
SERVICE_ROLE = os.environ.get("SERVICE_ROLE", "app")
FAULT_DIR = Path("/runtime/faults")
BUCKETS = [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]

STATE = {
    "started_at": time.time(),
    "lock": threading.Lock(),
    "counts": defaultdict(int),
    "lat_sum": 0.0,
    "lat_count": 0,
    "buckets": defaultdict(int),
}


def fault_path(service: str) -> Path:
    return FAULT_DIR / f"{service}.json"


def load_fault(service: str) -> dict | None:
    path = fault_path(service)
    if not path.exists():
        return None
    try:
        fault = json.loads(path.read_text())
    except Exception:
        return None
    now = time.time()
    if now > float(fault.get("end_ts", now)):
        return None
    return fault


def active_faults() -> list[dict]:
    faults = []
    own = load_fault(SERVICE)
    if own:
        faults.append(own)

    dns_fault = load_fault("dns-resolver")
    if dns_fault and SERVICE != "dns-resolver":
        faults.append(dns_fault)

    db_fault = load_fault("payment-db")
    if db_fault and SERVICE == "payment-svc":
        faults.append(db_fault)

    checkout_fault = load_fault("checkout-svc")
    if checkout_fault and SERVICE == "payment-svc":
        faults.append(checkout_fault)

    return faults


def baseline_gauges() -> dict[str, float]:
    uptime = max(time.time() - STATE["started_at"], 1.0)
    return {
        "service_cpu_pressure_ratio": 0.25,
        "service_memory_pressure_ratio": 0.35,
        "service_disk_pressure_ratio": 0.40,
        "service_ingestion_lag_seconds": 0.50,
        "service_time_skew_seconds": 0.0,
        "service_dns_latency_seconds": 0.02,
        "service_partition_active": 0.0,
        "container_memory_usage_bytes": 256_000_000.0,
        "container_cpu_usage_seconds_total": uptime * 0.15,
    }


def apply_fault_effects(lat_ms: float, status: int) -> tuple[float, int, dict[str, float]]:
    gauges = baseline_gauges()
    for fault in active_faults():
        ft = fault["fault_type"]

        if ft == "availability" and fault["target"] == SERVICE:
            lat_ms += 50
            status = 503
        elif ft == "latency" and fault["target"] == SERVICE:
            lat_ms += 500
        elif ft == "network_loss" and fault["target"] == SERVICE:
            lat_ms += 80
            if random.random() < 0.30:
                status = 502
        elif ft == "cpu_saturation" and fault["target"] == SERVICE:
            gauges["service_cpu_pressure_ratio"] = 0.95
            gauges["container_cpu_usage_seconds_total"] *= 6
            lat_ms += 700
        elif ft == "memory" and fault["target"] == SERVICE:
            gauges["service_memory_pressure_ratio"] = 0.95
            gauges["container_memory_usage_bytes"] = 950_000_000.0
            if random.random() < 0.20:
                status = 500
        elif ft == "disk_fill" and fault["target"] == SERVICE:
            gauges["service_disk_pressure_ratio"] = 0.95
            gauges["service_ingestion_lag_seconds"] = 20.0
        elif ft == "time_skew" and fault["target"] == SERVICE:
            gauges["service_time_skew_seconds"] = 60.0
            if random.random() < 0.50:
                status = 401
        elif ft == "network_partition" and fault["target"] == SERVICE:
            gauges["service_partition_active"] = 1.0
            lat_ms += 1200
            status = 504
        elif ft == "dns_latency" and fault["target"] == "dns-resolver":
            if SERVICE == "dns-resolver":
                gauges["service_dns_latency_seconds"] = 2.0
            else:
                lat_ms += 300
                if random.random() < 0.10:
                    status = 502
        elif ft == "http_error" and fault["target"] == SERVICE:
            if random.random() < 0.20:
                status = 500
        elif ft == "http_error" and fault["target"] == "checkout-svc" and SERVICE == "payment-svc":
            lat_ms += 250
            if random.random() < 0.15:
                status = 500

    return lat_ms, status, gauges


def observe(latency_seconds: float, status: int) -> None:
    with STATE["lock"]:
        STATE["counts"][status] += 1
        STATE["lat_sum"] += latency_seconds
        STATE["lat_count"] += 1
        for bucket in BUCKETS:
            if latency_seconds <= bucket:
                STATE["buckets"][bucket] += 1
        STATE["buckets"][float("inf")] += 1


def metrics_payload() -> str:
    gauges = baseline_gauges()
    for fault in active_faults():
        _, _, gauges = apply_fault_effects(0.0, 200)

    with STATE["lock"]:
        counts = dict(STATE["counts"])
        buckets = dict(STATE["buckets"])
        lat_sum = STATE["lat_sum"]
        lat_count = STATE["lat_count"]

    lines = [
        "# TYPE http_requests_total counter",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f'http_requests_total{{service="{SERVICE}",status="{status}"}} {count}')

    lines.append("# TYPE http_request_duration_seconds histogram")
    cumulative = 0
    for bucket in BUCKETS:
        cumulative = buckets.get(bucket, 0)
        lines.append(
            f'http_request_duration_seconds_bucket{{service="{SERVICE}",le="{bucket}"}} {cumulative}'
        )
    lines.append(
        f'http_request_duration_seconds_bucket{{service="{SERVICE}",le="+Inf"}} {buckets.get(float("inf"), 0)}'
    )
    lines.append(f'http_request_duration_seconds_sum{{service="{SERVICE}"}} {lat_sum}')
    lines.append(f'http_request_duration_seconds_count{{service="{SERVICE}"}} {lat_count}')

    for metric, value in gauges.items():
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f'{metric}{{service="{SERVICE}",role="{SERVICE_ROLE}"}} {value}')

    for fault in active_faults():
        lines.append("# TYPE service_fault_active gauge")
        lines.append(
            f'service_fault_active{{service="{SERVICE}",fault_type="{fault["fault_type"]}"}} 1'
        )

    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            status = 200
            for fault in active_faults():
                if fault["fault_type"] == "availability" and fault["target"] == SERVICE:
                    status = 503
                    break
            if status == 200:
                self._json(200, {"status": "ok", "service": SERVICE})
            else:
                self._json(503, {"status": "degraded", "service": SERVICE})
            return

        if self.path == "/metrics":
            payload = metrics_payload().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path != "/":
            self._json(404, {"error": "not_found"})
            return

        latency_ms = max(1.0, random.gauss(BASE_LAT_MS, JITTER_MS))
        status = 500 if random.random() < FAIL_RATE else 200
        latency_ms, status, _ = apply_fault_effects(latency_ms, status)
        latency_seconds = latency_ms / 1000.0
        time.sleep(latency_seconds)
        observe(latency_seconds, status)

        if status >= 400:
            self._json(status, {"service": SERVICE, "status": status, "error": "fault"})
            return
        self._json(200, {"service": SERVICE, "latency_ms": round(latency_ms, 2)})

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    FAULT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE} listening on {PORT}", flush=True)
    server.serve_forever()
