import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import urllib.request

RUNTIME = Path("/runtime")
STATE_FILE = RUNTIME / "state.json"
EVENTS_FILE = RUNTIME / "events.jsonl"
ALERTS_FILE = RUNTIME / "alerts.jsonl"
RCA_FILE = RUNTIME / "rca.json"
PORT = 8000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def append_event(source: str, event: str, **fields) -> None:
    payload = {"ts": utc_now(), "source": source, "event": event}
    payload.update(fields)
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def append_alert(alert: dict) -> None:
    with ALERTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(alert) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def correlate_alerts(window: int) -> list[dict]:
    cutoff = int(time.time()) - window
    alerts = [a for a in read_jsonl(ALERTS_FILE) if int(a.get("fire_ts", 0)) >= cutoff]
    grouped: dict[str, list[dict]] = {}
    for alert in alerts:
        grouped.setdefault(alert.get("service", "unknown"), []).append(alert)

    incidents = []
    for service, rows in grouped.items():
        rows = sorted(rows, key=lambda row: int(row.get("fire_ts", 0)))
        incidents.append({
            "incident_id": f"{service}-{rows[0].get('fire_ts', 0)}",
            "service": service,
            "window_seconds": window,
            "window_start": rows[0].get("fire_ts", 0),
            "window_end": rows[-1].get("fire_ts", 0),
            "alerts": [
                {
                    "alertname": row.get("alertname") or row.get("name"),
                    "severity": row.get("severity"),
                }
                for row in rows
            ],
            "count": len(rows),
        })
    return incidents


def sample_metrics() -> dict:
    try:
        with urllib.request.urlopen('http://api:8888/metrics', timeout=2) as resp:
            text = resp.read().decode()
    except Exception:
        return {}
    out = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        metric, value = line.split()[:2]
        out[metric.split('{', 1)[0]] = float(value)
    return out


def loop() -> None:
    alert_sent = False
    rca_written = False
    while True:
        state = read_json(STATE_FILE, {"evil_regex_active": False})
        metrics = sample_metrics()
        if state.get("evil_regex_active") and metrics.get('edge_last_latency_ms', 0.0) > 2000 and not alert_sent:
            ts = int(time.time())
            alert = {
                "fire_ts": ts,
                "timestamp": ts,
                "name": "HighLatencyRegex",
                "alertname": "HighLatencyRegex",
                "service": "regex-edge",
                "severity": "critical"
            }
            append_alert(alert)
            append_event('pipeline', 'alert_fired', alertname='HighLatencyRegex', service='regex-edge')
            alert_sent = True
        if alert_sent and not rca_written:
            rca = {
                "root_cause_service": "regex-edge",
                "confidence": 0.88,
                "failure_mode": "catastrophic_backtracking",
                "reason": "regex evaluation latency spiked before edge-wide failure"
            }
            RCA_FILE.write_text(json.dumps(rca), encoding='utf-8')
            append_event('pipeline', 'rca_ready', root='regex-edge')
            rca_written = True
        if not state.get("evil_regex_active") and alert_sent:
            alert_sent = False
            rca_written = False
        time.sleep(1)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            self._json(200, {"status": "ok"})
            return
        if parsed.path == '/alerts':
            since = int(parse_qs(parsed.query).get('since', ['0'])[0])
            alerts = [a for a in read_jsonl(ALERTS_FILE) if int(a.get('fire_ts', 0)) >= since]
            self._json(200, alerts)
            return
        if parsed.path == '/correlate':
            window = int(parse_qs(parsed.query).get('window', ['60'])[0])
            incidents = correlate_alerts(window)
            self._json(200, {"incidents": incidents, "count": len(incidents)})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == '/rca':
            self._json(200, read_json(RCA_FILE, {}))
            return
        self._json(404, {"error": "not_found"})

    def _json(self, status: int, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    RUNTIME.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=loop, daemon=True).start()
    append_event('pipeline', 'pipeline_started')
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
