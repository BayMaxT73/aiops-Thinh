from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from decision import select_action
from features import extract_features
from retrieval import retrieve_and_vote


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.exists():
        return path
    alt = Path("data-pack") / path
    if alt.exists():
        return alt
    return path


def decide(incident_path: Path, history_path: Path, actions_path: Path) -> dict:
    incident = json.loads(incident_path.read_text())
    history = json.loads(history_path.read_text())
    actions_catalog = yaml.safe_load(actions_path.read_text())

    query_vec = extract_features(incident)
    retrieval_result = retrieve_and_vote(query_vec, history)
    decision = select_action(retrieval_result, actions_catalog, query_vec, env="development", dry_run=True, min_precedents=0)

    return {
        "incident_id": incident_path.stem,
        "selected_action": decision["selected_action"],
        "params": decision["params"],
        "confidence": round(float(decision["confidence"]), 6),
        "top_3_neighbors": retrieval_result.get("neighbours", [])[:3],
        "consensus_score": round(float(decision.get("consensus_score", 0.0)), 6),
        "evidence": {
            "query_summary": {
                "trigger_svc": query_vec.get("trigger_svc"),
                "trigger_rule": query_vec.get("trigger_rule"),
                "trace_primary_target": query_vec.get("trace_primary_target"),
                "affected_svcs": sorted(query_vec.get("affected_svcs", set())),
                "max_error_rate": query_vec.get("max_error_rate"),
                "max_p99_ratio": query_vec.get("max_p99_ratio"),
                "log_templates": query_vec.get("log_templates", [])[:6],
                "metric_deltas": query_vec.get("metric_deltas", [])[:6],
            },
            "retrieval": {
                "best_sim": retrieval_result.get("best_sim"),
                "is_ood": retrieval_result.get("is_ood"),
                "neighbors": retrieval_result.get("neighbours", []),
                "candidates": [
                    {
                        "action": candidate["action"],
                        "vote_score": candidate["vote_score"],
                        "confidence": candidate["confidence"],
                        "evidence": candidate["evidence"],
                    }
                    for candidate in retrieval_result.get("candidates", [])
                ],
            },
            "decision": decision["evidence"],
        },
        "blast_radius_check": decision.get("blast_radius_check", {}),
        "selected_action_meta": decision.get("selected_action_meta", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("--incident", required=True)
    decide_parser.add_argument("--history", default="incidents_history.json")
    decide_parser.add_argument("--actions", default="actions.yaml")
    args = parser.parse_args()

    if args.cmd != "decide":
        parser.print_help()
        return 1

    output = decide(
        _resolve_path(args.incident),
        _resolve_path(args.history),
        _resolve_path(args.actions),
    )
    print(json.dumps(output, indent=2))
    with Path("audit.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(output) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
