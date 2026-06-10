from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOGGER = logging.getLogger("aiops.serve")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
D1_RESULTS_PATH = REPO_ROOT / "w2" / "d1" / "results" / "cluster_summary.json"
SERVICES_PATH = REPO_ROOT / "w2" / "d2" / "dataset" / "services.json"
HISTORY_PATH = REPO_ROOT / "w2" / "d2" / "dataset" / "incidents_history.json"

SEVERITY_ORDER = {"info": 0, "warning": 1, "warn": 1, "critical": 2, "crit": 2}
VALID_CLASSES = {
    "connection_pool_exhaustion",
    "slow_query",
    "memory_leak",
    "rebalance_storm",
    "deadlock",
    "network_partition",
    "bad_deploy",
    "config_push",
    "tls_expiry",
    "ddos",
    "lock_contention",
    "eviction",
    "infinite_retry",
    "model_drift",
    "rate_limit_misconfig",
    "thread_starvation",
    "cache_stampede",
    "n_plus_1",
    "downstream_provider",
    "batch_overlap",
    "feature_flag",
    "cache_cold_start",
    "replication_lag",
    "vacuum_storm",
    "other",
}
CLASS_MAP = {label: label for label in VALID_CLASSES if label != "other"}


class AlertModel(BaseModel):
    id: str
    ts: str
    service: str
    metric: str
    severity: str
    value: float | int
    threshold: float | int
    labels: dict[str, Any] = Field(default_factory=dict)


class IncidentRequest(BaseModel):
    alerts: list[AlertModel]


class RootCauseModel(BaseModel):
    service: str
    class_name: str = Field(alias="class")
    confidence: float
    reasoning: str
    method: str

    model_config = {"populate_by_name": True}


class ClusterModel(BaseModel):
    cluster_id: str
    alert_count: int
    services: list[str]
    time_range: list[str]
    max_severity: str
    fingerprints: list[str]


class IncidentResponse(BaseModel):
    clusters: list[ClusterModel]
    root_cause: RootCauseModel
    recommended_actions: list[str]
    similar_incidents: list[str]


def parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(alert: dict[str, Any]) -> str:
    return f"{alert['service']}|{alert['metric']}|{alert['severity']}"


def load_graph_payload(path: Path) -> dict[str, Any]:
    return load_json(path)


def build_undirected_graph(payload: dict[str, Any]) -> dict[str, set[str]]:
    edges = payload["edges"] if isinstance(payload, dict) and "edges" in payload else payload
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = edge.get("source", edge.get("from"))
        target = edge.get("target", edge.get("to"))
        if not source or not target or edge.get("type") == "kafka":
            continue
        graph[source].add(target)
        graph[target].add(source)
    if isinstance(payload, dict):
        for key in ("nodes", "services", "stores"):
            for node in payload.get(key, []):
                node_name = node["name"] if isinstance(node, dict) else node
                graph.setdefault(node_name, set())
    return dict(graph)


def build_directed_graph(payload: dict[str, Any]) -> tuple[nx.DiGraph, dict[str, str]]:
    graph = nx.DiGraph()
    node_types: dict[str, str] = {}
    for service in payload.get("services", []):
        graph.add_node(service["name"])
        node_types[service["name"]] = "service"
    for store in payload.get("stores", []):
        graph.add_node(store["name"])
        node_types[store["name"]] = store.get("type", "store")
    for edge in payload.get("edges", []):
        source = edge.get("source", edge.get("from"))
        target = edge.get("target", edge.get("to"))
        if source and target:
            graph.add_edge(source, target, edge_type=edge.get("type", "unknown"))
    return graph, node_types


def shortest_path_with_limit(graph: dict[str, set[str]], source: str, target: str, max_hop: int) -> int | None:
    if source == target:
        return 0
    if source not in graph or target not in graph:
        return None
    frontier = [(source, 0)]
    seen = {source}
    while frontier:
        node, distance = frontier.pop(0)
        if distance >= max_hop:
            continue
        for neighbor in graph.get(node, set()):
            if neighbor == target:
                return distance + 1
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append((neighbor, distance + 1))
    return None


def session_groups(alerts: list[dict[str, Any]], gap_sec: int = 120) -> list[list[dict[str, Any]]]:
    if not alerts:
        return []
    ordered = sorted(alerts, key=lambda item: parse_ts(item["ts"]))
    groups = [[ordered[0]]]
    for alert in ordered[1:]:
        previous = groups[-1][-1]
        gap = (parse_ts(alert["ts"]) - parse_ts(previous["ts"])).total_seconds()
        if gap <= gap_sec:
            groups[-1].append(alert)
        else:
            groups.append([alert])
    return groups


def topology_group(alerts: list[dict[str, Any]], graph: dict[str, set[str]], max_hop: int = 2) -> list[list[dict[str, Any]]]:
    isolated_alerts: list[list[dict[str, Any]]] = []
    by_service: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in alerts:
        note = str(alert.get("labels", {}).get("note", "")).lower()
        if "unrelated" in note or "noise" in note or "independent" in note:
            isolated_alerts.append([alert])
            continue
        by_service[alert["service"]].append(alert)

    services = list(by_service)
    parent = {service: service for service in services}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for index, left in enumerate(services):
        for right in services[index + 1 :]:
            distance = shortest_path_with_limit(graph, left, right, max_hop=max_hop)
            if distance is not None and distance <= max_hop:
                union(left, right)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for service, items in by_service.items():
        grouped[find(service)].extend(items)
    return list(grouped.values()) + isolated_alerts


def max_severity(alerts: list[dict[str, Any]]) -> str:
    return max(alerts, key=lambda item: SEVERITY_ORDER.get(item["severity"].lower(), -1))["severity"]


def summarize_cluster(cluster_id: str, alerts: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(alerts, key=lambda item: parse_ts(item["ts"]))
    return {
        "cluster_id": cluster_id,
        "alert_count": len(ordered),
        "services": sorted({item["service"] for item in ordered}),
        "time_range": [ordered[0]["ts"], ordered[-1]["ts"]],
        "max_severity": max_severity(ordered),
        "fingerprints": sorted({item["fingerprint"] for item in ordered}),
        "alert_ids": [item["id"] for item in ordered],
    }


def correlate(alerts: list[dict[str, Any]], graph: dict[str, set[str]], gap_sec: int = 120, max_hop: int = 2) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    sessions = session_groups(alerts, gap_sec=gap_sec)
    for session_index, session in enumerate(sessions, start=1):
        groups = topology_group(session, graph, max_hop=max_hop)
        for group_index, group in enumerate(groups):
            cluster_id = f"c-{session_index:03d}-{group_index:03d}"
            clusters.append(summarize_cluster(cluster_id, group))
    return sorted(clusters, key=lambda item: item["time_range"][0])


def normalize_scores(raw_scores: dict[str, float]) -> dict[str, float]:
    if not raw_scores:
        return {}
    max_score = max(raw_scores.values()) or 1.0
    return {node: score / max_score for node, score in raw_scores.items()}


def pagerank_scores(subgraph: nx.DiGraph) -> dict[str, float]:
    if subgraph.number_of_nodes() == 1:
        node = next(iter(subgraph.nodes()))
        return {node: 1.0}
    return normalize_scores(nx.pagerank(subgraph, alpha=0.85))


def timestamp_scores(cluster: dict[str, Any], alert_lookup: dict[str, dict[str, Any]]) -> dict[str, float]:
    first_seen: dict[str, datetime] = {}
    for alert_id in cluster.get("alert_ids", []):
        alert = alert_lookup[alert_id]
        service = alert["service"]
        current_ts = parse_ts(alert["ts"])
        if service not in first_seen or current_ts < first_seen[service]:
            first_seen[service] = current_ts
    ordered = sorted(first_seen.items(), key=lambda item: item[1])
    if not ordered:
        return {service: 1.0 for service in cluster["services"]}
    if len(ordered) == 1 or ordered[0][1] == ordered[-1][1]:
        return {service: 1.0 for service in first_seen}
    min_ts = ordered[0][1]
    max_ts = ordered[-1][1]
    span = (max_ts - min_ts).total_seconds() or 1.0
    scores = {}
    for service, first_ts in first_seen.items():
        lag = (first_ts - min_ts).total_seconds()
        scores[service] = max(0.0, 1 - (lag / span))
    return scores


def apply_store_refinement(
    scores: dict[str, float],
    cluster: dict[str, Any],
    alert_lookup: dict[str, dict[str, Any]],
    node_types: dict[str, str],
) -> dict[str, float]:
    if not scores:
        return scores
    top_service = max(scores, key=scores.get)
    if node_types.get(top_service, "service") == "service":
        return scores
    store_first_seen = None
    app_first_seen = None
    for alert_id in cluster.get("alert_ids", []):
        alert = alert_lookup[alert_id]
        ts = parse_ts(alert["ts"])
        if alert["service"] == top_service:
            store_first_seen = ts if store_first_seen is None or ts < store_first_seen else store_first_seen
        elif node_types.get(alert["service"], "service") == "service":
            app_first_seen = ts if app_first_seen is None or ts < app_first_seen else app_first_seen
    if store_first_seen and app_first_seen and store_first_seen > app_first_seen:
        scores[top_service] *= 0.6
    return scores


def graph_rank_cluster(
    cluster: dict[str, Any],
    graph: nx.DiGraph,
    node_types: dict[str, str],
    alert_lookup: dict[str, dict[str, Any]],
) -> list[list[Any]]:
    services = cluster["services"]
    subgraph = graph.subgraph(services).copy()
    if subgraph.number_of_nodes() == 0:
        subgraph.add_nodes_from(services)
    pr_scores = pagerank_scores(subgraph)
    ts_scores = timestamp_scores(cluster, alert_lookup)
    final_scores = {}
    for service in services:
        final_scores[service] = 0.6 * pr_scores.get(service, 0.0) + 0.4 * ts_scores.get(service, 0.0)
    final_scores = apply_store_refinement(final_scores, cluster, alert_lookup, node_types)
    ranked = sorted(final_scores.items(), key=lambda item: (-item[1], item[0]))
    return [[service, round(score, 2)] for service, score in ranked[:3]]


def normalize_severity(value: str) -> str:
    mapping = {"crit": "critical", "critical": "critical", "warn": "high", "warning": "high", "info": "low"}
    return mapping.get(value.lower(), value.lower())


def tokenize_cluster(cluster: dict[str, Any]) -> set[str]:
    tokens = set()
    for service in cluster["services"]:
        tokens.update(service.replace("-", " ").replace("_", " ").split())
    for fp in cluster.get("fingerprints", []):
        tokens.update(fp.lower().replace("|", " ").replace("_", " ").replace("-", " ").split())
    return {token for token in tokens if token}


def tokenize_metric_hints(cluster: dict[str, Any]) -> set[str]:
    hints = set()
    allowed = {"pool", "connection", "db", "query", "cache", "queue", "lock", "redis", "kafka", "timeout"}
    for fp in cluster.get("fingerprints", []):
        parts = fp.lower().split("|")
        if len(parts) >= 2:
            metric_tokens = parts[1].replace("_", " ").replace("-", " ").split()
            for token in metric_tokens:
                if token in allowed:
                    hints.add(token)
    return hints


def tokenize_incident(incident: dict[str, Any]) -> set[str]:
    text = " ".join(incident.get("services_involved", [])) + " " + incident.get("summary", "") + " " + incident.get("remediation", "")
    tokens = text.lower().replace("-", " ").replace("_", " ").replace("/", " ").split()
    return {token.strip(".,:;()") for token in tokens if token}


def keyword_similarity(cluster_tokens: set[str], incident_tokens: set[str]) -> float:
    if not cluster_tokens or not incident_tokens:
        return 0.0
    intersection = len(cluster_tokens & incident_tokens)
    union = len(cluster_tokens | incident_tokens)
    return intersection / union if union else 0.0


def retrieve_similar(cluster: dict[str, Any], root_candidate: str, incidents: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    cluster_tokens = tokenize_cluster(cluster)
    metric_hints = tokenize_metric_hints(cluster)
    cluster_services = set(cluster["services"])
    cluster_severity = normalize_severity(cluster["max_severity"])
    ranked: list[tuple[dict[str, Any], float]] = []
    for incident in incidents:
        incident_tokens = tokenize_incident(incident)
        score = 0.0
        if incident["root_cause_service"] in cluster_services:
            score += 0.4
        overlap = len(cluster_services & set(incident.get("services_involved", [])))
        score += min(0.4, 0.2 * overlap)
        if incident.get("severity", "").lower() == cluster_severity:
            score += 0.2
        if incident["root_cause_service"] == root_candidate:
            score += 0.25
        score += 0.2 * keyword_similarity(cluster_tokens, incident_tokens)
        if metric_hints:
            hint_overlap = len(metric_hints & incident_tokens)
            score += min(0.15, 0.05 * hint_overlap)
        if score >= 0.2:
            ranked.append((incident, round(score, 3)))
    ranked.sort(key=lambda item: (-item[1], item[0]["id"]))
    return ranked[:3]


def remediation_to_actions(text: str) -> list[str]:
    parts = re.split(r";|\.(?=\s+[A-Z])", text)
    actions = [part.strip() for part in parts if part.strip()]
    return actions[:3] or ["Investigate manually"]


def classify_from_retrieval(similar_incidents: list[tuple[dict[str, Any], float]]) -> tuple[str, list[str], list[str]]:
    if not similar_incidents:
        return "other", ["Investigate manually"], []
    top_incident, _ = similar_incidents[0]
    mapped_class = CLASS_MAP.get(top_incident["root_cause_class"], "other")
    actions = remediation_to_actions(top_incident.get("remediation", ""))
    incident_ids = [incident["id"] for incident, _ in similar_incidents]
    return mapped_class, actions, incident_ids


def build_reasoning(root_cause: str, confidence: float, similar_ids: list[str]) -> str:
    if similar_ids:
        return f"{root_cause} ranked #1 (score={confidence:.2f}) by PageRank+timestamp. Similar to {similar_ids[0]}."
    return f"{root_cause} ranked #1 (score={confidence:.2f}) by PageRank+timestamp. No similar incident found."


def build_fallback(cluster: dict[str, Any], graph_top3: list[list[Any]], reason: str) -> dict[str, Any]:
    root_cause = graph_top3[0][0] if graph_top3 else cluster["services"][0]
    confidence = float(graph_top3[0][1]) if graph_top3 else 0.0
    return {
        "cluster_id": cluster["cluster_id"],
        "graph_top3": graph_top3 or [[root_cause, round(confidence, 2)]],
        "root_cause": root_cause,
        "class": "other",
        "confidence": round(max(0.0, min(confidence, 1.0)), 2),
        "actions": ["Investigate manually"],
        "reasoning": reason,
        "similar_incidents": [],
        "method": "graph-only-fallback",
    }


def validate_result(result: dict[str, Any], cluster: dict[str, Any]) -> tuple[bool, str]:
    if not result.get("graph_top3"):
        return False, "graph_top3 empty"
    if not isinstance(result.get("similar_incidents", []), list):
        return False, "similar_incidents not list"
    if not isinstance(result.get("actions", []), list) or not result.get("actions"):
        return False, "actions invalid"
    if not isinstance(result.get("reasoning", ""), str) or not result.get("reasoning", "").strip():
        return False, "reasoning empty"
    if result.get("root_cause") not in cluster["services"]:
        return False, "root_cause outside cluster"
    if result.get("class") not in VALID_CLASSES:
        return False, "class outside enum"
    confidence = result.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        return False, "confidence outside range"
    return True, "ok"


def prepare_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared = []
    for alert in alerts:
        item = dict(alert)
        item["ts"] = item.get("ts") or item.get("timestamp")
        item["fingerprint"] = fingerprint(item)
        prepared.append(item)
    return prepared


GRAPH_PAYLOAD = load_graph_payload(SERVICES_PATH)
UNDIRECTED_GRAPH = build_undirected_graph(GRAPH_PAYLOAD)
DIRECTED_GRAPH, NODE_TYPES = build_directed_graph(GRAPH_PAYLOAD)
HISTORY = load_json(HISTORY_PATH)["incidents"]
D1_SUMMARY = load_json(D1_RESULTS_PATH)


def process_batch(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    prepared_alerts = prepare_alerts(alerts)
    clusters = correlate(prepared_alerts, UNDIRECTED_GRAPH, gap_sec=120, max_hop=2)
    if not clusters:
        return {
            "clusters": [],
            "root_cause": {
                "service": "unknown",
                "class": "other",
                "confidence": 0.0,
                "reasoning": "No clusters produced from input batch.",
                "method": "graph-only-fallback",
            },
            "recommended_actions": ["Investigate manually"],
            "similar_incidents": [],
        }

    alert_lookup = {alert["id"]: alert for alert in prepared_alerts}
    primary_cluster = max(clusters, key=lambda item: item["alert_count"])
    graph_top3 = graph_rank_cluster(primary_cluster, DIRECTED_GRAPH, NODE_TYPES, alert_lookup)
    root_cause = graph_top3[0][0] if graph_top3 else primary_cluster["services"][0]
    confidence = float(graph_top3[0][1]) if graph_top3 else 0.0
    similar = retrieve_similar(primary_cluster, root_cause, HISTORY)
    class_name, actions, similar_ids = classify_from_retrieval(similar)
    reasoning = build_reasoning(root_cause, confidence, similar_ids)

    result = {
        "cluster_id": primary_cluster["cluster_id"],
        "graph_top3": graph_top3,
        "root_cause": root_cause,
        "class": class_name,
        "confidence": round(max(0.0, min(confidence, 1.0)), 2),
        "actions": actions,
        "reasoning": reasoning,
        "similar_incidents": similar_ids,
        "method": "graph+retrieval",
    }
    valid, reason = validate_result(result, primary_cluster)
    if not valid:
        result = build_fallback(primary_cluster, graph_top3, f"Fallback because {reason}.")

    return {
        "clusters": [
            {
                "cluster_id": cluster["cluster_id"],
                "alert_count": cluster["alert_count"],
                "services": cluster["services"],
                "time_range": cluster["time_range"],
                "max_severity": cluster["max_severity"],
                "fingerprints": cluster["fingerprints"],
            }
            for cluster in clusters
        ],
        "root_cause": {
            "service": result["root_cause"],
            "class": result["class"],
            "confidence": result["confidence"],
            "reasoning": result["reasoning"],
            "method": result["method"],
        },
        "recommended_actions": result["actions"],
        "similar_incidents": result["similar_incidents"],
    }


app = FastAPI(title="AIOps Incident Service", version="0.1.0")


@app.middleware("http")
async def latency_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
    LOGGER.info("%s %s %s %.2fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    checks = {
        "graph_loaded": bool(UNDIRECTED_GRAPH) and DIRECTED_GRAPH.number_of_nodes() > 0,
        "history_loaded": len(HISTORY) > 0,
        "d1_summary_present": D1_SUMMARY.get("input_alerts", 0) > 0,
    }
    if not all(checks.values()):
        raise HTTPException(status_code=503, detail=checks)
    return {"status": "ready", **checks}


@app.post("/incident", response_model=IncidentResponse)
def incident(request: IncidentRequest) -> IncidentResponse:
    alerts = [item.model_dump() for item in request.alerts]
    if not alerts:
        raise HTTPException(status_code=400, detail="alerts must not be empty")
    try:
        payload = process_batch(alerts)
        return IncidentResponse.model_validate(payload)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        LOGGER.exception("Failed to process incident batch: %s", exc)
        raise HTTPException(status_code=500, detail="incident pipeline failed") from exc
