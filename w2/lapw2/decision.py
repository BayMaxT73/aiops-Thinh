from __future__ import annotations

from collections import Counter

from features import is_infra_service


CONFIDENCE_THRESHOLDS = {
    "production": 0.70,
    "staging": 0.50,
    "development": 0.35,
}


def _catalog_by_name(catalog: list[dict]) -> dict[str, dict]:
    return {item["name"]: item for item in catalog}


def _service_votes(candidate: dict, query_vec: dict) -> tuple[str | None, list[dict]]:
    scores: Counter[str] = Counter()
    evidence: list[dict] = []

    for item in candidate.get("evidence", []):
        vote_weight = float(item.get("vote_weight", 0.0) or 0.0)
        hist_params = item.get("hist_params", [])
        if hist_params:
            service = hist_params[0]
            scores[service] += vote_weight * 2.0
            evidence.append({"service": service, "source": "hist_params", "weight": round(vote_weight * 2.0, 6)})

        for svc in item.get("affected_svcs", []):
            extra = 1.0 if svc == query_vec.get("trigger_svc") else 0.0
            weight = vote_weight * (0.5 + extra)
            scores[svc] += weight
            evidence.append({"service": svc, "source": "affected_svcs", "weight": round(weight, 6)})

    inferred = scores.most_common(1)[0][0] if scores else None
    query_services = set(query_vec.get("affected_svcs", set()))

    if inferred and inferred not in query_services:
        if query_vec.get("trace_primary_target") and not is_infra_service(query_vec["trace_primary_target"]):
            inferred = query_vec["trace_primary_target"]
        elif query_vec.get("trigger_svc") in query_services:
            inferred = query_vec.get("trigger_svc")

    trace_primary = query_vec.get("trace_primary_target")
    if trace_primary and inferred != trace_primary and query_vec.get("max_error_rate", 0.0) >= 0.20:
        inferred = trace_primary
        evidence.append({"service": trace_primary, "source": "trace_override", "weight": round(query_vec["max_error_rate"], 6)})

    return inferred, evidence


def _top_neighbor_service(retrieval_result: dict) -> str | None:
    scores: Counter[str] = Counter()
    for candidate in retrieval_result.get("candidates", []):
        for item in candidate.get("evidence", []):
            hist_params = item.get("hist_params", [])
            if hist_params:
                scores[hist_params[0]] += float(item.get("vote_weight", 0.0) or 0.0)
    return scores.most_common(1)[0][0] if scores else None


def _page_decision(
    reason: str,
    retrieval_result: dict,
    action_meta: dict | None = None,
    extra_evidence: dict | None = None,
    dry_run: bool = True,
    env: str = "production",
) -> dict:
    evidence = {
        "reason": reason,
        "best_sim": retrieval_result.get("best_sim", 0.0),
        "neighbors_considered": retrieval_result.get("neighbours", []),
    }
    if extra_evidence:
        evidence.update(extra_evidence)
    return {
        "selected_action": "page_oncall",
        "params": {"team": "platform-team"},
        "confidence": max(0.3, round(retrieval_result.get("best_sim", 0.0), 6)),
        "consensus_score": round(
            next((c["confidence"] for c in retrieval_result.get("candidates", []) if c["action"] == "page_oncall"), 0.0),
            6,
        ),
        "evidence": evidence,
        "blast_radius_check": {"passed": True, "reason": "manual escalation"},
        "selected_action_meta": action_meta or {},
        "dry_run": dry_run,
        "environment": env,
        "execution_mode": "notify_only",
        "auto_execute": False,
    }


def _map_params(action: str, service: str | None) -> dict:
    if action == "rollback_service":
        return {"service": service, "target_version": "previous"}
    if action == "increase_pool_size":
        return {"service": service}
    if action == "restart_pod":
        return {"service": service, "pod_selector": f"app={service}"}
    if action == "dns_config_rollback":
        return {"configmap_name": "coredns", "target_revision": "previous"}
    if action == "network_policy_revert":
        return {"policy_name": "default-deny"}
    return {"team": "platform-team"}


def _env_threshold(env: str) -> float:
    return CONFIDENCE_THRESHOLDS.get(env, CONFIDENCE_THRESHOLDS["production"])


def select_action(
    retrieval_result: dict,
    catalog: list[dict],
    query_vec: dict,
    env: str = "production",
    dry_run: bool = True,
    min_precedents: int = 5,
) -> dict:
    catalog_by_name = _catalog_by_name(catalog)
    page_meta = catalog_by_name.get("page_oncall", {})
    min_confidence = _env_threshold(env)

    if retrieval_result.get("is_ood"):
        return _page_decision("ood", retrieval_result, page_meta, {"ood": True}, dry_run=dry_run, env=env)

    trace_primary = query_vec.get("trace_primary_target")
    top_neighbor_service = _top_neighbor_service(retrieval_result)
    if (
        trace_primary
        and not is_infra_service(trace_primary)
        and trace_primary != query_vec.get("trigger_svc")
        and top_neighbor_service
        and top_neighbor_service != trace_primary
    ):
        return _page_decision(
            "conflicting_evidence",
            retrieval_result,
            page_meta,
            {
                "trace_primary_target": trace_primary,
                "top_neighbor_service": top_neighbor_service,
            },
            dry_run=dry_run,
            env=env,
        )

    scored_candidates: list[dict] = []
    rejected: list[dict] = []

    for candidate in retrieval_result.get("candidates", []):
        action = candidate["action"]
        if action == "page_oncall":
            continue

        action_meta = catalog_by_name.get(action)
        if not action_meta:
            rejected.append({"action": action, "reason": "missing_from_catalog"})
            continue

        confidence = float(candidate.get("confidence", 0.0) or 0.0)
        blast_radius = int(action_meta.get("blast_radius_services", 0) or 0)
        successful_precedents = int(candidate.get("successful_precedent_count", 0) or 0)

        if confidence < 0.25:
            rejected.append({"action": action, "reason": "low_confidence", "confidence": round(confidence, 6)})
            continue
        if blast_radius >= 3 and confidence < 0.55:
            rejected.append({"action": action, "reason": "blast_radius_gate", "confidence": round(confidence, 6)})
            continue
        if blast_radius >= 2 and confidence < 0.35:
            rejected.append({"action": action, "reason": "blast_radius_gate", "confidence": round(confidence, 6)})
            continue
        if confidence < min_confidence:
            rejected.append({"action": action, "reason": "environment_threshold", "confidence": round(confidence, 6), "threshold": min_confidence})
            continue
        if successful_precedents < min_precedents:
            rejected.append({"action": action, "reason": "insufficient_precedents", "successful_precedent_count": successful_precedents})
            continue

        total_vote_weight = float(candidate.get("total_vote_weight", 0.0) or 0.0)
        success_vote_score = float(candidate.get("success_vote_score", 0.0) or 0.0)
        p_success = success_vote_score / total_vote_weight if total_vote_weight else 0.0
        utility = p_success * confidence - 0.005 * float(action_meta.get("cost_min", 0.0) or 0.0)
        combined = utility + 0.05 * float(candidate.get("vote_score", 0.0) or 0.0)
        service, service_evidence = _service_votes(candidate, query_vec)

        scored_candidates.append(
            {
                "action": action,
                "candidate_confidence": round(confidence, 6),
                "vote_score": round(float(candidate.get("vote_score", 0.0) or 0.0), 6),
                "p_success": round(p_success, 6),
                "utility": round(utility, 6),
                "combined": round(combined, 6),
                "service": service,
                "service_evidence": service_evidence,
                "blast_radius_services": blast_radius,
                "cost_min": action_meta.get("cost_min", 0),
                "successful_precedent_count": successful_precedents,
                "action_meta": action_meta,
            }
        )

    scored_candidates.sort(key=lambda item: item["combined"], reverse=True)

    if len(scored_candidates) >= 2:
        top = scored_candidates[0]
        second = scored_candidates[1]
        if top["combined"] > 0:
            gap = abs(top["combined"] - second["combined"]) / top["combined"]
            ambiguous_root_causes = {
                neighbor["root_cause"]
                for neighbor in retrieval_result.get("neighbours", [])
                if neighbor.get("sim", 0.0) >= 0.20
            }
            if gap < 0.14 and top["combined"] < 0.55 and len(ambiguous_root_causes) > 1:
                return _page_decision(
                    "near_tie",
                    retrieval_result,
                    page_meta,
                    {
                        "top_candidates": [
                            {"action": top["action"], "combined": top["combined"]},
                            {"action": second["action"], "combined": second["combined"]},
                        ],
                        "rejected": rejected,
                    },
                    dry_run=dry_run,
                    env=env,
                )

    if not scored_candidates:
        return _page_decision(
            "no_surviving_candidates",
            retrieval_result,
            page_meta,
            {"rejected": rejected},
            dry_run=dry_run,
            env=env,
        )

    winner = scored_candidates[0]
    params = _map_params(winner["action"], winner["service"])

    return {
        "selected_action": winner["action"],
        "params": params,
        "confidence": round(winner["candidate_confidence"], 6),
        "consensus_score": round(winner["candidate_confidence"], 6),
        "evidence": {
            "reason": "selected_best_candidate",
            "best_sim": retrieval_result.get("best_sim", 0.0),
            "trace_primary_target": trace_primary,
            "winner": {
                "action": winner["action"],
                "service": winner["service"],
                "p_success": winner["p_success"],
                "utility": winner["utility"],
                "combined": winner["combined"],
                "successful_precedent_count": winner["successful_precedent_count"],
            },
            "service_inference": winner["service_evidence"],
            "candidate_scores": [
                {
                    "action": item["action"],
                    "combined": item["combined"],
                    "utility": item["utility"],
                    "p_success": item["p_success"],
                    "confidence": item["candidate_confidence"],
                    "successful_precedent_count": item["successful_precedent_count"],
                }
                for item in scored_candidates
            ],
            "rejected": rejected,
            "environment_threshold": min_confidence,
        },
        "blast_radius_check": {
            "passed": True,
            "blast_radius_services": winner["blast_radius_services"],
            "cost_min": winner["cost_min"],
        },
        "selected_action_meta": winner["action_meta"],
        "dry_run": dry_run,
        "environment": env,
        "execution_mode": "log_only" if dry_run else "apply",
        "auto_execute": not dry_run,
    }


__all__ = ["CONFIDENCE_THRESHOLDS", "select_action"]
