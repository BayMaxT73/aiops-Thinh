from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from statistics import median
from typing import Any, Iterable, Protocol, TypedDict

try:
    from drain3 import TemplateMiner  # type: ignore
except ImportError:  # pragma: no cover - optional dependency in local tests
    TemplateMiner = Any  # type: ignore


class _TemplateMinerProtocol(Protocol):
    def add_log_message(self, message: str) -> Any: ...


class QueryVector(TypedDict):
    log_templates: list[str]
    trace_hot_edges: list[dict]
    affected_svcs: set[str]
    trigger_svc: str | None
    trigger_rule: str | None
    max_error_rate: float
    max_p99_ratio: float
    metric_deltas: list[dict]
    trace_primary_target: str | None
    precursor_signals: list[dict]


UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ISO_TS_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[t ][0-9:.+-z]+\b", re.I)
DURATION_RE = re.compile(r"\b\d+(?:\.\d+)?(?:ms|s|sec|secs|m|min|mins|h|hr|hrs)\b", re.I)
LONG_NUMBER_RE = re.compile(r"\b\d{3,}\b")
KEY_VALUE_RE = re.compile(r"\b([a-z0-9_.-]+)=([^\s,;]+)", re.I)
ANGLE_BRACKET_RE = re.compile(r"<[^>]+>")
NON_WORD_RE = re.compile(r"[^a-z0-9_:\-./() ]+")
WHITESPACE_RE = re.compile(r"\s+")

INFRA_NAMES = {"kafka-events", "edge-lb"}
ERROR_LEVELS = {"error", "warn", "warning", "fatal", "critical"}


def _parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _safe_median(values: Iterable[float], default: float = 0.0) -> float:
    values = list(values)
    return median(values) if values else default


def is_infra_service(service: str | None) -> bool:
    if not service:
        return False
    return service in INFRA_NAMES or service.endswith("-db") or service.endswith("-redis")


def normalize_log_message(message: str) -> str:
    text = message.lower()
    text = ISO_TS_RE.sub(" <var> ", text)
    text = UUID_RE.sub(" <var> ", text)
    text = IP_RE.sub(" <var> ", text)
    text = DURATION_RE.sub(" <var> ", text)
    text = KEY_VALUE_RE.sub(lambda match: f"{match.group(1)}=<var>", text)
    text = ANGLE_BRACKET_RE.sub(" <var> ", text)
    text = LONG_NUMBER_RE.sub(" <var> ", text)
    text = NON_WORD_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def _metric_service(series_name: str) -> str:
    return series_name.split(".", 1)[0]


def _metric_name(series_name: str) -> str:
    return series_name.split(".", 1)[1] if "." in series_name else series_name


def _extract_template_from_drain_result(result: Any) -> str | None:
    if result is None:
        return None
    if hasattr(result, "cluster_id"):
        cluster = getattr(result, "cluster_id", None)
        if cluster is None:
            return None
    if hasattr(result, "cluster") and getattr(result, "cluster", None) is not None:
        template = getattr(result.cluster, "get_template", None)
        if callable(template):
            return str(template())
        if hasattr(result.cluster, "log_template"):
            return str(result.cluster.log_template)
    if isinstance(result, dict):
        if isinstance(result.get("template_mined"), str):
            return result["template_mined"]
        cluster = result.get("cluster")
        if cluster is not None and hasattr(cluster, "log_template"):
            return str(cluster.log_template)
        if isinstance(cluster, dict) and isinstance(cluster.get("log_template"), str):
            return cluster["log_template"]
    if isinstance(result, tuple) and len(result) >= 2:
        cluster = result[1]
        if hasattr(cluster, "log_template"):
            return str(cluster.log_template)
    return None


def _extract_log_templates(logs: list[dict], drain_miner: _TemplateMinerProtocol | TemplateMiner | None) -> list[str]:
    templates: list[str] = []
    for entry in logs:
        message = entry.get("msg", "")
        normalized = normalize_log_message(message)
        if not normalized:
            continue
        template = None
        if drain_miner is not None:
            try:
                template = _extract_template_from_drain_result(drain_miner.add_log_message(normalized))
            except Exception:
                template = None
        templates.append(template or normalized)
    counter = Counter(templates)
    return [template for template, _ in counter.most_common(20)]


def _build_trace_hot_edges(traces: list[dict]) -> tuple[list[dict], float, float, str | None]:
    if not traces:
        return [], 0.0, 0.0, None

    sorted_traces = sorted(traces, key=lambda item: _parse_ts(item["ts"]))
    cutoff = max(1, len(sorted_traces) // 3)

    baseline_by_edge: dict[tuple[str, str], list[float]] = defaultdict(list)
    for item in sorted_traces[:cutoff]:
        edge = (item["from"], item["to"])
        p99_ms = float(item.get("p99_ms", 0.0) or 0.0)
        if p99_ms > 0:
            baseline_by_edge[edge].append(p99_ms)

    hot_edges: list[dict] = []
    cumulative_service_error: Counter[str] = Counter()
    max_error_rate = 0.0
    max_p99_ratio = 0.0

    for item in sorted_traces:
        edge = (item["from"], item["to"])
        p99_ms = float(item.get("p99_ms", 0.0) or 0.0)
        baseline = _safe_median(baseline_by_edge.get(edge), default=p99_ms or 1.0)
        baseline = max(baseline, 1.0)
        error_rate = float(item.get("error_count", 0.0) or 0.0) / max(float(item.get("count", 0.0) or 0.0), 1.0)
        p99_ratio = p99_ms / baseline if p99_ms > 0 else 1.0

        if error_rate >= 0.05 or p99_ratio >= 1.5:
            target = item["from"] if is_infra_service(item["to"]) else item["to"]
            cumulative_service_error[target] += error_rate
            max_error_rate = max(max_error_rate, error_rate)
            max_p99_ratio = max(max_p99_ratio, p99_ratio)
            hot_edges.append(
                {
                    "from": item["from"],
                    "to": item["to"],
                    "error_rate": round(error_rate, 4),
                    "p99_ratio": round(p99_ratio, 4),
                    "count": item.get("count", 0),
                    "ts": item.get("ts"),
                }
            )

    primary_target = cumulative_service_error.most_common(1)[0][0] if cumulative_service_error else None
    return hot_edges, max_error_rate, max_p99_ratio, primary_target


def _metric_records_from_incident(incident: dict) -> dict[str, list[list[Any]]]:
    metrics_window = incident.get("metrics_window", {})
    if isinstance(metrics_window, dict) and isinstance(metrics_window.get("samples"), dict):
        return metrics_window["samples"]

    metric_records = incident.get("metrics", [])
    samples: dict[str, list[list[Any]]] = defaultdict(list)
    for record in metric_records:
        service = record.get("service")
        metric = record.get("metric")
        ts = record.get("ts")
        value = record.get("value")
        if service and metric and value is not None:
            samples[f"{service}.{metric}"].append([ts, value])
    return dict(samples)


def _build_metric_deltas(samples: dict[str, list[list[Any]]]) -> list[dict]:
    metric_deltas: list[dict] = []

    for series_name, points in samples.items():
        values = [float(point[1]) for point in points if len(point) >= 2 and point[1] is not None]
        if len(values) < 3:
            continue
        baseline_count = max(1, len(values) // 3)
        baseline = _safe_median(values[:baseline_count], default=values[0])
        peak = max(values)
        ratio = peak / max(abs(baseline), 1e-6)
        if ratio >= 2.0:
            metric_deltas.append(
                {
                    "service": _metric_service(series_name),
                    "metric": _metric_name(series_name),
                    "baseline": round(baseline, 4),
                    "peak": round(peak, 4),
                    "ratio": round(ratio, 4),
                }
            )

    metric_deltas.sort(key=lambda item: item["ratio"], reverse=True)
    return metric_deltas


def _extract_precursor_signals(incident: dict) -> list[dict]:
    trigger = incident.get("trigger_alert", {})
    trigger_ts = incident.get("trigger_ts") or trigger.get("ts")
    trigger_dt = _parse_ts(trigger_ts) if isinstance(trigger_ts, str) else None
    precursor_signals: list[dict] = []

    raw_precursors = incident.get("precursor_signals") or incident.get("metric_alerts") or []
    for signal in raw_precursors:
        z_score = float(signal.get("z_score", 0.0) or 0.0)
        if z_score < 2.5:
            continue

        signal_ts = signal.get("ts")
        minutes_before_trigger = signal.get("minutes_before_trigger")
        if minutes_before_trigger is None and trigger_dt and isinstance(signal_ts, str):
            minutes_before_trigger = round((trigger_dt - _parse_ts(signal_ts)).total_seconds() / 60.0, 2)

        precursor_signals.append(
            {
                "service": signal.get("service"),
                "metric": signal.get("metric"),
                "z_score": round(z_score, 4),
                "ts": signal_ts,
                "alert_level": signal.get("alert_level", "precursor"),
                "minutes_before_trigger": minutes_before_trigger,
            }
        )

    precursor_signals.sort(
        key=lambda item: (
            -(float(item["z_score"]) if item.get("z_score") is not None else 0.0),
            float(item["minutes_before_trigger"]) if item.get("minutes_before_trigger") is not None else 9999.0,
        )
    )
    return precursor_signals


def _derive_affected_svcs(incident: dict, hot_edges: list[dict], metric_deltas: list[dict], precursor_signals: list[dict]) -> set[str]:
    affected_svcs: set[str] = set()
    trigger = incident.get("trigger_alert", {})
    trigger_svc = trigger.get("service")
    if trigger_svc:
        affected_svcs.add(trigger_svc)

    for edge in hot_edges:
        affected_svcs.add(edge["from"])
        affected_svcs.add(edge["to"])
        if is_infra_service(edge["to"]):
            affected_svcs.add(edge["from"])

    for entry in incident.get("logs", []):
        svc = entry.get("svc")
        level = str(entry.get("level", "")).lower()
        if svc and level in ERROR_LEVELS:
            affected_svcs.add(svc)

    for metric in metric_deltas:
        affected_svcs.add(metric["service"])

    for signal in precursor_signals:
        if signal.get("service"):
            affected_svcs.add(signal["service"])

    return affected_svcs


def extract_features(incident: dict, drain_miner: _TemplateMinerProtocol | TemplateMiner | None = None) -> QueryVector:
    logs = incident.get("logs", [])
    traces = incident.get("traces", [])
    trigger = incident.get("trigger_alert", {})
    metric_samples = _metric_records_from_incident(incident)

    log_templates = _extract_log_templates(logs, drain_miner)
    hot_edges, max_error_rate, max_p99_ratio, trace_primary_target = _build_trace_hot_edges(traces)
    metric_deltas = _build_metric_deltas(metric_samples)
    precursor_signals = _extract_precursor_signals(incident)
    affected_svcs = _derive_affected_svcs(incident, hot_edges, metric_deltas, precursor_signals)

    return {
        "log_templates": log_templates,
        "trace_hot_edges": hot_edges,
        "affected_svcs": affected_svcs,
        "trigger_svc": trigger.get("service"),
        "trigger_rule": trigger.get("rule_id"),
        "max_error_rate": round(max_error_rate, 4),
        "max_p99_ratio": round(max_p99_ratio, 4),
        "metric_deltas": metric_deltas,
        "trace_primary_target": trace_primary_target,
        "precursor_signals": precursor_signals,
    }


__all__ = [
    "TemplateMiner",
    "extract_features",
    "is_infra_service",
    "normalize_log_message",
]
