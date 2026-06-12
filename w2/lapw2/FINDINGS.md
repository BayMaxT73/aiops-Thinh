# FINDINGS

## 1. Similarity function

I used the required weighted hybrid similarity:

- `0.40 * log_sim`
- `0.35 * trace_sim`
- `0.15 * svc_sim`
- `0.10 * metric_sim`

The main reason was schema mismatch between live and history data: raw logs in eval JSONs and cleaned templates in history. I considered exact template matching for logs, but it was too brittle. On `E01`, exact matching gave `log_sim = 0.0` against both pool-exhaustion precedents `INC-2025-11-08` and `INC-2025-09-05`, because the live templates were `failed to forward request to t24-service: pool exhausted` and `connectionpool: timeout acquiring connection (waited var ) attempt var`, while history only stored shortened templates. The word-overlap matcher preserved that signal and the final lab run graded `8/8`.

## 2. Outcome-weighted voting vs pure similarity

The clearest case was `E05`. Pure similarity voting produced:

- `rollback_service = 0.785`
- `increase_pool_size = 0.555`
- `restart_pod = 0.225`

Outcome-weighted voting changed that to:

- `rollback_service = 0.670`
- `increase_pool_size = 0.555`
- `restart_pod = 0.225`

The drop came from `INC-2026-05-10`, a `partial` pool-exhaustion incident, which only counted at `0.5x`. That did not flip top-1 on this eval set, but it cut rollback's lead over `increase_pool_size` from `0.230` to `0.115`, which is exactly the ambiguity that made the engine escalate `E05` to `page_oncall` instead of over-committing.

## 3. Full EV calculation

I used `E01` for the full calculation because it auto-acted successfully.

Candidate set after retrieval:

- `increase_pool_size`: `vote_score=0.573333`, `confidence=0.396770`
- `rollback_service`: `vote_score=0.679999`, `confidence=0.470588`

Expected-value terms:

- `increase_pool_size`: `P_success = 0.573333 / 0.573333 = 1.0`; cost `= 1`
- `rollback_service`: `P_success = 0.573333 / 0.679999 = 0.843138`; cost `= 10`

Utility:

- `increase_pool_size`: `1.0 * 0.396770 - 0.005 * 1 = 0.391770`
- `rollback_service`: `0.843138 * 0.470588 - 0.005 * 10 = 0.346771`

Combined score:

- `increase_pool_size`: `0.391770 + 0.05 * 0.573333 = 0.420437`
- `rollback_service`: `0.346771 + 0.05 * 0.679999 = 0.380771`

`increase_pool_size` won by `0.039666`, and the grader accepted it for `E01`.

## 4. Escalations

The lab engine escalated on six incidents:

- `E02` at confidence `0.33`, reason `conflicting_evidence`
- `E04` at confidence `0.30`, reason `ood`
- `E05` at confidence `0.325`, reason `near_tie`
- `E06` at confidence `0.334286`, reason `conflicting_evidence`
- `E07` at confidence `0.60`, reason `ood`
- `E08` at confidence `0.30`, reason `ood`

All six were correct against `eval/expected.json`, because every one of those incidents accepts `page_oncall`. The two non-escalations were also correct: `E01 -> increase_pool_size` and `E03 -> rollback_service`.

## 5. Most likely breakage class

The most likely breakage class is novel infra or control-plane incidents that reuse familiar service edges but have new semantics, basically the `E07` shape. In my run, `E07` still had `best_sim = 0.60` because it shared the `checkout-svc -> inventory-svc` edge and the same affected service, even though the real pattern was `k8s_api_throttle` plus `informer-cache-stale`.

The concrete improvement would be a small topology-aware semantic reranker that scores trigger-rule tokens and log-template embeddings after the coarse weighted retrieval step. I did not implement that because the history corpus is only about 30 incidents, so adding a learned or embedding-heavy reranker would have been harder to calibrate than the current hand-auditable rules within the lab time budget.

## Note On Current Repo State

The repo now also contains live-mode scaffolding for Kafka, Redis, Qdrant, PostgreSQL, and Kubernetes execution. Those additions were not part of the original graded lab run above; the findings and numeric examples in this document refer specifically to the offline eval workflow driven by `engine.py` / `engine_compat.py` and `eval/E01` through `eval/E08`.
