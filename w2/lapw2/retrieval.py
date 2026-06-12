from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, TypedDict

from features import normalize_log_message


try:
    from qdrant_client import QdrantClient  # type: ignore
except ImportError:  # pragma: no cover - optional dependency in local tests
    QdrantClient = Any  # type: ignore


OUTCOME_WEIGHTS = {
    "success": 1.0,
    "partial": 0.5,
    "failed": 0.1,
}

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "after",
    "before",
    "than",
    "over",
    "last",
    "this",
    "that",
    "var",
    "app",
    "svc",
}

VECTOR_SIZE = 128


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


class RetrievalResult(TypedDict):
    candidates: list[dict]
    neighbours: list[dict]
    is_ood: bool
    best_sim: float
    successful_precedent_count: int


def parse_history_action(action: str) -> tuple[str, list[str]]:
    parts = action.split(":")
    if not parts:
        return "page_oncall", []
    return parts[0], parts[1:]


def parse_metric_delta(delta: str) -> tuple[float, float]:
    try:
        before, after = [float(x.strip()) for x in delta.replace("->", "|").split("|")]
        return before, after
    except Exception:
        return 0.0, 0.0


def _words(text: str) -> set[str]:
    tokens = set()
    for token in normalize_log_message(text).replace("(", " ").replace(")", " ").split():
        token = token.strip(":,./")
        if len(token) < 3 or token in STOP_WORDS:
            continue
        if any(ch.isdigit() for ch in token) and token != "x509":
            continue
        tokens.add(token)
    return tokens


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def _log_similarity(query_templates: list[str], history_signatures: list[str]) -> float:
    if not query_templates or not history_signatures:
        return 0.0

    matches = 0
    hist_word_sets = [_words(signature) for signature in history_signatures]
    for template in query_templates:
        query_words = _words(template)
        if not query_words:
            continue
        if any(len(query_words & hist_words) >= 2 for hist_words in hist_word_sets):
            matches += 1
    return matches / max(len(query_templates), 1)


def _trace_similarity(query_edges: list[dict], history_edges: list[dict]) -> float:
    query_pairs = {
        (edge["from"], edge["to"])
        for edge in query_edges
        if edge.get("from") and edge.get("to")
    }
    history_pairs = {
        (edge["from"], edge["to"])
        for edge in history_edges
        if edge.get("from") and edge.get("to")
    }
    if not query_pairs and not history_pairs:
        return 0.0
    return len(query_pairs & history_pairs) / len(query_pairs | history_pairs)


def _history_metric_services(history_entry: dict) -> set[str]:
    services = set()
    for signature in history_entry.get("metric_signatures", []):
        before, after = parse_metric_delta(signature["delta"])
        ratio = after / max(abs(before), 1e-6)
        if ratio >= 2.0:
            services.add(signature["service"])
    return services


def similarity(query_vec: dict, history_entry: dict) -> dict:
    log_sim = _log_similarity(query_vec.get("log_templates", []), history_entry.get("log_signatures", []))
    trace_sim = _trace_similarity(query_vec.get("trace_hot_edges", []), history_entry.get("trace_signatures", []))
    svc_sim = _jaccard(query_vec.get("affected_svcs", set()), history_entry.get("affected_services", []))
    metric_sim = _jaccard(
        {metric["service"] for metric in query_vec.get("metric_deltas", [])},
        _history_metric_services(history_entry),
    )
    total = 0.40 * log_sim + 0.35 * trace_sim + 0.15 * svc_sim + 0.10 * metric_sim
    return {
        "similarity": round(total, 6),
        "log_sim": round(log_sim, 6),
        "trace_sim": round(trace_sim, 6),
        "svc_sim": round(svc_sim, 6),
        "metric_sim": round(metric_sim, 6),
    }


def _feature_tokens(query_vec: dict) -> list[str]:
    tokens: list[str] = []
    for template in query_vec.get("log_templates", []):
        for word in sorted(_words(template)):
            tokens.append(f"log:{word}")
    for edge in query_vec.get("trace_hot_edges", []):
        if edge.get("from") and edge.get("to"):
            tokens.append(f"trace:{edge['from']}->{edge['to']}")
    for svc in sorted(query_vec.get("affected_svcs", set())):
        tokens.append(f"svc:{svc}")
    for metric in query_vec.get("metric_deltas", []):
        if metric.get("service") and metric.get("metric"):
            tokens.append(f"metric:{metric['service']}:{metric['metric']}")
    for signal in query_vec.get("precursor_signals", []):
        if signal.get("service") and signal.get("metric"):
            tokens.append(f"precursor:{signal['service']}:{signal['metric']}")
    if query_vec.get("trigger_svc"):
        tokens.append(f"trigger:{query_vec['trigger_svc']}")
    if query_vec.get("trigger_rule"):
        tokens.append(f"rule:{query_vec['trigger_rule']}")
    return tokens


def _hash_token(token: str, vector_size: int) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % vector_size


def build_embedding(query_vec: dict, vector_size: int = VECTOR_SIZE) -> list[float]:
    vector = [0.0] * vector_size
    for token in _feature_tokens(query_vec):
        vector[_hash_token(token, vector_size)] += 1.0

    norm = sum(value * value for value in vector) ** 0.5
    if norm > 0:
        vector = [round(value / norm, 6) for value in vector]
    return vector


def _serialize_history_entry(incident: dict, outcome: str, query_vec: QueryVector | dict | None = None) -> dict:
    source = query_vec or incident

    log_signatures = incident.get("log_signatures") or source.get("log_templates", [])

    trace_signatures = incident.get("trace_signatures")
    if trace_signatures is None:
        trace_signatures = [
            {
                "from": edge["from"],
                "to": edge["to"],
                "p99_deviation_ratio": edge.get("p99_ratio", 1.0),
                "error_rate": edge.get("error_rate", 0.0),
            }
            for edge in source.get("trace_hot_edges", [])
            if edge.get("from") and edge.get("to")
        ]

    metric_signatures = incident.get("metric_signatures")
    if metric_signatures is None:
        metric_signatures = [
            {
                "service": metric["service"],
                "metric": metric["metric"],
                "delta": f"{metric.get('baseline', 0)} -> {metric.get('peak', 0)}",
            }
            for metric in source.get("metric_deltas", [])
            if metric.get("service") and metric.get("metric")
        ]

    return {
        "id": incident.get("id") or incident.get("incident_id"),
        "root_cause_class": incident.get("root_cause_class"),
        "affected_services": sorted(incident.get("affected_services") or source.get("affected_svcs", [])),
        "log_signatures": log_signatures,
        "trace_signatures": trace_signatures,
        "metric_signatures": metric_signatures,
        "actions_taken": incident.get("actions_taken", []),
        "outcome": outcome or incident.get("outcome", "failed"),
        "mttr_minutes": incident.get("mttr_minutes"),
    }


class IncidentRetriever:
    def __init__(self, qdrant_client: QdrantClient, collection: str = "incidents", vector_size: int = VECTOR_SIZE):
        self.qdrant_client = qdrant_client
        self.collection = collection
        self.vector_size = vector_size

    def upsert_incident(self, incident: dict, outcome: str, query_vec: QueryVector | dict | None = None) -> None:
        payload = _serialize_history_entry(incident, outcome, query_vec=query_vec)
        point_id = payload["id"] or hashlib.md5(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        vector_source = query_vec or incident
        vector = build_embedding(vector_source, vector_size=self.vector_size)
        self.qdrant_client.upsert(
            collection_name=self.collection,
            points=[
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": payload,
                }
            ],
        )

    def _search(self, query_vec: dict, limit: int) -> list[Any]:
        query_vector = build_embedding(query_vec, vector_size=self.vector_size)
        try:
            return list(
                self.qdrant_client.search(
                    collection_name=self.collection,
                    query_vector=query_vector,
                    limit=limit,
                    with_payload=True,
                )
            )
        except TypeError:
            return list(
                self.qdrant_client.search(
                    self.collection,
                    query_vector,
                    limit=limit,
                    with_payload=True,
                )
            )

    def retrieve_and_vote(self, query_vec: dict, top_k: int = 5) -> dict:
        ann_hits = self._search(query_vec, limit=max(top_k * 3, 15))
        scored_neighbors: list[dict] = []

        for hit in ann_hits:
            payload = getattr(hit, "payload", None) or hit.get("payload", {})
            if not payload:
                continue
            sims = similarity(query_vec, payload)
            scored_neighbors.append(
                {
                    "id": payload["id"],
                    "sim": sims["similarity"],
                    "outcome": payload.get("outcome", "failed"),
                    "root_cause": payload.get("root_cause_class"),
                    "history_entry": payload,
                    "signal_breakdown": sims,
                    "ann_score": round(float(getattr(hit, "score", None) or hit.get("score", 0.0) or 0.0), 6),
                }
            )

        return _vote_on_scored_neighbors(query_vec, scored_neighbors, top_k=top_k, use_weak_semantic_match=False)


def _vote_on_scored_neighbors(
    query_vec: QueryVector | dict,
    scored_neighbors: list[dict],
    top_k: int,
    use_weak_semantic_match: bool,
) -> RetrievalResult:
    scored_neighbors.sort(key=lambda item: (item["sim"], item.get("ann_score", 0.0)), reverse=True)
    best_sim = scored_neighbors[0]["sim"] if scored_neighbors else 0.0
    top_breakdown = scored_neighbors[0]["signal_breakdown"] if scored_neighbors else {}
    neighbors = [item for item in scored_neighbors[:top_k] if item["sim"] >= 0.15]
    is_ood = best_sim < 0.20 or (
        top_breakdown.get("log_sim", 0.0) == 0.0
        and query_vec.get("max_error_rate", 0.0) < 0.05
        and (not use_weak_semantic_match or query_vec.get("max_p99_ratio", 0.0) < 2.0)
    )

    vote_buckets: dict[str, dict] = {}
    successful_precedent_count = 0

    for neighbor in neighbors:
        entry = neighbor["history_entry"]
        outcome = entry.get("outcome", "failed")
        outcome_weight = OUTCOME_WEIGHTS.get(outcome, 0.1)
        vote_weight = neighbor["sim"] * outcome_weight
        if vote_weight <= 0:
            continue
        if outcome == "success":
            successful_precedent_count += 1

        for action_string in entry.get("actions_taken", []):
            action_name, hist_params = parse_history_action(action_string)
            bucket = vote_buckets.setdefault(
                action_name,
                {
                    "action": action_name,
                    "vote_score": 0.0,
                    "success_vote_score": 0.0,
                    "total_vote_weight": 0.0,
                    "confidence": 0.0,
                    "successful_precedent_count": 0,
                    "evidence": [],
                },
            )
            bucket["vote_score"] += vote_weight
            bucket["total_vote_weight"] += vote_weight
            if outcome == "success":
                bucket["success_vote_score"] += vote_weight
                bucket["successful_precedent_count"] += 1
            bucket["evidence"].append(
                {
                    "neighbor_id": entry["id"],
                    "similarity": neighbor["sim"],
                    "outcome": outcome,
                    "vote_weight": round(vote_weight, 6),
                    "hist_params": hist_params,
                    "affected_svcs": entry.get("affected_services", []),
                    "root_cause": entry.get("root_cause_class"),
                    "signal_breakdown": neighbor["signal_breakdown"],
                    "ann_score": round(float(neighbor.get("ann_score", 0.0) or 0.0), 6),
                }
            )

    candidates = list(vote_buckets.values())
    denom = sum(candidate["vote_score"] for candidate in candidates)
    for candidate in candidates:
        candidate["confidence"] = round(candidate["vote_score"] / denom, 6) if denom else 0.0
        candidate["vote_score"] = round(candidate["vote_score"], 6)
        candidate["success_vote_score"] = round(candidate["success_vote_score"], 6)
        candidate["total_vote_weight"] = round(candidate["total_vote_weight"], 6)
    candidates.sort(key=lambda item: item["vote_score"], reverse=True)

    return {
        "candidates": candidates,
        "neighbours": [
            {
                "id": item["id"],
                "sim": round(item["sim"], 6),
                "outcome": item["outcome"],
                "root_cause": item["root_cause"],
                "ann_score": round(float(item.get("ann_score", 0.0) or 0.0), 6),
            }
            for item in neighbors
        ],
        "is_ood": is_ood,
        "best_sim": round(best_sim, 6),
        "successful_precedent_count": successful_precedent_count,
    }


def retrieve_and_vote(query_vec: QueryVector | dict, history: list[dict], top_k: int = 5) -> RetrievalResult:
    scored_neighbors: list[dict] = []
    for entry in history:
        sims = similarity(query_vec, entry)
        scored_neighbors.append(
            {
                "id": entry["id"],
                "sim": sims["similarity"],
                "outcome": entry.get("outcome", "failed"),
                "root_cause": entry.get("root_cause_class"),
                "history_entry": entry,
                "signal_breakdown": sims,
                "ann_score": 0.0,
            }
        )
    return _vote_on_scored_neighbors(query_vec, scored_neighbors, top_k=top_k, use_weak_semantic_match=True)


__all__ = [
    "IncidentRetriever",
    "OUTCOME_WEIGHTS",
    "build_embedding",
    "parse_history_action",
    "parse_metric_delta",
    "retrieve_and_vote",
    "similarity",
]
