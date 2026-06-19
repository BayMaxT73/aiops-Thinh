import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


RUNTIME = Path("/runtime")
FAULT_DIR = RUNTIME / "faults"
ALERT_HISTORY = RUNTIME / "alert_history.jsonl"
FAULT_HISTORY = RUNTIME / "fault_history.jsonl"
PORT = 8000


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def active_faults() -> list[dict]:
    now = time.time()
    faults = []
    for path in FAULT_DIR.glob("*.json"):
        try:
            fault = json.loads(path.read_text())
        except Exception:
            continue
        if now <= float(fault.get("end_ts", 0)):
            faults.append(fault)
    return faults


def alerts_since(since_ts: int) -> list[dict]:
    return [row for row in read_jsonl(ALERT_HISTORY) if int(row.get("fire_ts", 0)) >= since_ts]


def root_for_fault(fault: dict) -> tuple[str | None, str]:
    target = fault.get("target")
    ft = fault.get("fault_type")
    if ft == "http_error" and target == "checkout-svc":
        return "payment-svc", "symptom-carrier remap"
    if ft == "dns_latency":
        return "api-gateway", "intentional raw misattribution for topology normalization"
    return target, "direct fault target"


def rca_for_window(window_start: int, window_end: int) -> dict:
    candidates = [
        row
        for row in read_jsonl(FAULT_HISTORY)
        if window_start <= int(row.get("start_ts", 0)) <= window_end
    ]
    if not candidates:
        return {"root_cause_service": None, "confidence": 0.0, "reason": "no fault in window"}
    latest = sorted(candidates, key=lambda row: row["start_ts"])[-1]
    root, reason = root_for_fault(latest)
    return {
        "root_cause_service": root,
        "confidence": 0.95 if root else 0.0,
        "fault_type": latest.get("fault_type"),
        "target": latest.get("target"),
        "reason": reason,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "active_faults": len(active_faults())})
            return
        if parsed.path == "/alerts":
            params = parse_qs(parsed.query)
            since_ts = int(params.get("since", ["0"])[0])
            self._json(200, alerts_since(since_ts))
            return
        if parsed.path == "/metrics":
            body = b"pipeline_up 1\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            payload = {}

        if parsed.path == "/rca":
            start_ts = int(payload.get("window_start", 0))
            end_ts = int(payload.get("window_end", int(time.time())))
            self._json(200, rca_for_window(start_ts, end_ts))
            return

        if parsed.path == "/correlate":
            alerts = alerts_since(int(time.time()) - int(payload.get("window", 300)))
            grouped: dict[str, list[str]] = {}
            for alert in alerts:
                grouped.setdefault(alert["service"], []).append(alert["alertname"])
            self._json(200, {"groups": grouped, "count": len(alerts)})
            return

        self._json(404, {"error": "not_found"})

    def _json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    FAULT_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"pipeline listening on {PORT}", flush=True)
    server.serve_forever()

