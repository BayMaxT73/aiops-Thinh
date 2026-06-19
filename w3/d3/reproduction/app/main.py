import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

EVIL = re.compile(r'(?:(?:"|\d|.*)+(?:.*=.*))')
RUNTIME = Path("/runtime")
STATE_FILE = RUNTIME / "state.json"
EVENTS_FILE = RUNTIME / "events.jsonl"
METRICS_FILE = RUNTIME / "metrics.json"
app = FastAPI()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"evil_regex_active": False}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def read_metrics() -> dict:
    if not METRICS_FILE.exists():
        return {"requests": 0, "errors": 0, "last_latency_ms": 0.0}
    return json.loads(METRICS_FILE.read_text(encoding="utf-8"))


def write_metrics(metrics: dict) -> None:
    METRICS_FILE.write_text(json.dumps(metrics), encoding="utf-8")


def log_event(event_type: str, **fields) -> None:
    payload = {"ts": utc_now(), "source": "app", "event": event_type}
    payload.update(fields)
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/metrics")
def metrics():
    m = read_metrics()
    body = "\n".join([
        "# TYPE edge_last_latency_ms gauge",
        f'edge_last_latency_ms{{service="regex-edge"}} {m["last_latency_ms"]}',
        "# TYPE edge_error_total counter",
        f'edge_error_total{{service="regex-edge"}} {m["errors"]}',
        "# TYPE edge_request_total counter",
        f'edge_request_total{{service="regex-edge"}} {m["requests"]}',
        "",
    ])
    return PlainTextResponse(body)


@app.get("/")
async def root(request: Request):
    state = read_state()
    metrics = read_metrics()
    metrics["requests"] += 1
    q = str(request.url.query)
    if state.get("evil_regex_active"):
        log_event("regex_rule_active", service="regex-edge")
        t0 = time.time()
        EVIL.match(q)
        elapsed = max(time.time() - t0, 2.6)
        if elapsed < 2.6:
            time.sleep(2.6 - elapsed)
            elapsed = 2.6
        metrics["errors"] += 1
        metrics["last_latency_ms"] = round(elapsed * 1000, 1)
        write_metrics(metrics)
        log_event("user_visible_timeout", service="regex-edge", latency_ms=metrics["last_latency_ms"])
        return JSONResponse({"ok": False, "latency_ms": metrics["last_latency_ms"]}, status_code=503)
    metrics["last_latency_ms"] = 35.0
    write_metrics(metrics)
    return {"ok": True}


if __name__ == "__main__":
    RUNTIME.mkdir(parents=True, exist_ok=True)
    write_metrics({"requests": 0, "errors": 0, "last_latency_ms": 0.0})
    log_event("service_started", service="regex-edge")
