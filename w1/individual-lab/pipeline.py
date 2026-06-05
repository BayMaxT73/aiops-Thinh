import argparse
import json
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Deque, Dict, List, Optional


ALERTS_FILE = Path("alerts.jsonl")


class StreamingAnomalyDetector:
    def __init__(
        self,
        baseline_window: int = 12,
        warmup_samples: int = 8,
        suspicion_threshold: int = 2,
        cooldown_ticks: int = 6,
    ) -> None:
        self.baseline_window = baseline_window
        self.warmup_samples = warmup_samples
        self.suspicion_threshold = suspicion_threshold
        self.cooldown_ticks = cooldown_ticks
        self.tick = 0
        self.history: Deque[Dict[str, float]] = deque(maxlen=baseline_window)
        self.suspicion_counts = {
            "memory_leak": 0,
            "traffic_spike": 0,
            "dependency_timeout": 0,
        }
        self.last_alert_tick = {
            "memory_leak": -cooldown_ticks,
            "traffic_spike": -cooldown_ticks,
            "dependency_timeout": -cooldown_ticks,
        }

    def process(self, timestamp: str, metrics: Dict[str, float], logs: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        self.tick += 1
        baseline = self._baseline()
        alert = None

        if baseline is not None:
            alert = self._detect(timestamp, metrics, logs, baseline)

        self.history.append(metrics)
        return alert

    def _baseline(self) -> Optional[Dict[str, float]]:
        if len(self.history) < self.warmup_samples:
            return None

        totals: Dict[str, float] = {}
        for sample in self.history:
            for key, value in sample.items():
                totals[key] = totals.get(key, 0.0) + float(value)

        return {key: value / len(self.history) for key, value in totals.items()}

    def _detect(
        self,
        timestamp: str,
        metrics: Dict[str, float],
        logs: List[Dict[str, str]],
        baseline: Dict[str, float],
    ) -> Optional[Dict[str, str]]:
        memory_score = self._memory_leak_score(metrics, logs, baseline)
        traffic_score = self._traffic_spike_score(metrics, logs, baseline)
        dependency_score = self._dependency_timeout_score(metrics, logs, baseline)

        memory_signal = memory_score >= 4
        traffic_signal = traffic_score >= 5
        dependency_signal = dependency_score >= 4

        signals = {
            "memory_leak": memory_signal,
            "traffic_spike": traffic_signal,
            "dependency_timeout": dependency_signal,
        }

        for fault_type, active in signals.items():
            self.suspicion_counts[fault_type] = self.suspicion_counts[fault_type] + 1 if active else 0

        if self.suspicion_counts["dependency_timeout"] >= self.suspicion_threshold:
            return self._build_alert(timestamp, "dependency_timeout", metrics, baseline)
        if self.suspicion_counts["traffic_spike"] >= self.suspicion_threshold:
            return self._build_alert(timestamp, "traffic_spike", metrics, baseline)
        if self.suspicion_counts["memory_leak"] >= self.suspicion_threshold:
            return self._build_alert(timestamp, "memory_leak", metrics, baseline)

        return None

    def _memory_leak_score(
        self,
        metrics: Dict[str, float],
        logs: List[Dict[str, str]],
        baseline: Dict[str, float],
    ) -> int:
        memory_utilization = metrics["memory_usage_bytes"] / max(metrics["memory_limit_bytes"], 1)
        score = 0
        if memory_utilization >= 0.82:
            score += 2
        if metrics["memory_usage_bytes"] >= baseline["memory_usage_bytes"] * 1.18:
            score += 1
        if metrics["jvm_gc_pause_ms_avg"] >= max(35.0, baseline["jvm_gc_pause_ms_avg"] * 2.2):
            score += 2
        if metrics["cpu_usage_percent"] >= baseline["cpu_usage_percent"] + 10:
            score += 1
        if metrics["http_p99_latency_ms"] >= baseline["http_p99_latency_ms"] + 120:
            score += 1
        if metrics["http_5xx_rate"] >= max(3.0, baseline["http_5xx_rate"] + 2.5):
            score += 1
        if self._logs_contain(logs, ("OutOfMemoryWarning", "GC pause exceeded threshold")):
            score += 2
        return score

    def _traffic_spike_score(
        self,
        metrics: Dict[str, float],
        logs: List[Dict[str, str]],
        baseline: Dict[str, float],
    ) -> int:
        score = 0
        if metrics["http_requests_per_sec"] >= max(220.0, baseline["http_requests_per_sec"] * 2.0):
            score += 2
        if metrics["queue_depth"] >= max(30.0, baseline["queue_depth"] + 20.0):
            score += 1
        if metrics["http_p99_latency_ms"] >= max(220.0, baseline["http_p99_latency_ms"] + 150.0):
            score += 2
        if metrics["cpu_usage_percent"] >= baseline["cpu_usage_percent"] + 16.0:
            score += 1
        if metrics["http_5xx_rate"] >= max(3.0, baseline["http_5xx_rate"] + 2.5):
            score += 1
        if metrics["upstream_timeout_rate"] <= max(8.0, baseline["upstream_timeout_rate"] + 5.0):
            score += 1
        if self._logs_contain(logs, ("Queue depth high", "server overloaded")):
            score += 2
        return score

    def _dependency_timeout_score(
        self,
        metrics: Dict[str, float],
        logs: List[Dict[str, str]],
        baseline: Dict[str, float],
    ) -> int:
        score = 0
        if metrics["upstream_timeout_rate"] >= max(8.0, baseline["upstream_timeout_rate"] + 6.0):
            score += 2
        if metrics["upstream_timeout_rate"] >= max(15.0, baseline["upstream_timeout_rate"] * 4.0):
            score += 2
        if metrics["http_5xx_rate"] >= max(3.0, baseline["http_5xx_rate"] + 2.5):
            score += 1
        if metrics["http_p99_latency_ms"] >= max(220.0, baseline["http_p99_latency_ms"] + 160.0):
            score += 1
        if metrics["http_requests_per_sec"] >= baseline["http_requests_per_sec"] * 1.20:
            score += 1
        if metrics["queue_depth"] >= max(20.0, baseline["queue_depth"] + 12.0):
            score += 1
        if self._logs_contain(logs, ("Upstream timeout rate", "Circuit breaker OPEN")):
            score += 2
        return score

    def _build_alert(
        self,
        timestamp: str,
        fault_type: str,
        metrics: Dict[str, float],
        baseline: Dict[str, float],
    ) -> Optional[Dict[str, str]]:
        if self.tick - self.last_alert_tick[fault_type] < self.cooldown_ticks:
            return None

        self.last_alert_tick[fault_type] = self.tick
        self.suspicion_counts[fault_type] = 0

        if fault_type == "memory_leak":
            utilization = metrics["memory_usage_bytes"] / max(metrics["memory_limit_bytes"], 1) * 100
            severity = "critical" if utilization >= 88 or metrics["http_5xx_rate"] >= 10 else "warning"
            message = (
                f"Memory growth sustained: utilization={utilization:.0f}%, "
                f"gc_pause_ms={metrics['jvm_gc_pause_ms_avg']:.1f}, "
                f"baseline_memory={baseline['memory_usage_bytes'] / 1_000_000:.0f}MB"
            )
        elif fault_type == "traffic_spike":
            severity = "critical" if metrics["http_5xx_rate"] >= 8 or metrics["queue_depth"] >= 100 else "warning"
            message = (
                f"Traffic surge detected: rps={metrics['http_requests_per_sec']:.1f}, "
                f"queue_depth={metrics['queue_depth']}, "
                f"p99_ms={metrics['http_p99_latency_ms']:.1f}"
            )
        else:
            severity = "critical" if metrics["upstream_timeout_rate"] >= 25 or metrics["http_5xx_rate"] >= 8 else "warning"
            message = (
                f"Upstream dependency degrading: timeout_rate={metrics['upstream_timeout_rate']:.1f}%, "
                f"5xx_rate={metrics['http_5xx_rate']:.1f}%, "
                f"p99_ms={metrics['http_p99_latency_ms']:.1f}"
            )

        return {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "type": fault_type,
            "severity": severity,
            "message": message,
        }

    @staticmethod
    def _logs_contain(logs: List[Dict[str, str]], fragments: tuple[str, ...]) -> bool:
        for entry in logs:
            message = entry.get("message", "")
            if any(fragment in message for fragment in fragments):
                return True
        return False


detector = StreamingAnomalyDetector()


class IngestHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/ingest":
            self._send_json(404, {"status": "not_found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body)
            timestamp = payload["timestamp"]
            metrics = payload["metrics"]
            logs = payload.get("logs", [])
        except (json.JSONDecodeError, KeyError, TypeError):
            self._send_json(400, {"status": "bad_request"})
            return

        alert = detector.process(timestamp, metrics, logs)
        if alert:
            with ALERTS_FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(alert) + "\n")

        self._send_json(200, {"status": "ok"})

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, status_code: int, body: Dict[str, str]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description="Streaming anomaly detection pipeline")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), IngestHandler)
    print(f"[PIPELINE] Listening on http://{args.host}:{args.port}/ingest")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
