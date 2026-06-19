# Chaos Engineering Report - Thinh

## 1. Setup

- Stack: Docker stack defined in `docker-compose.yml`
- Pipeline API: `pipeline/mock_pipeline_api.py`
- Prometheus: `http://localhost:9190`
- Alertmanager: `http://localhost:9193`
- Total experiments run: `10`
- Time scale: `CHAOS_TIME_SCALE=0.1`

## 2. Results table

```text
==== Chaos Run ====
Total: 10
Detected: 10/10
RCA correct: 10/10
False alarms in baseline windows: 0
Precision: 1.00
Recall: 1.00
MTTD p50: 1.0s, p95: 1.0s

Per-experiment:
| # | name              | detected | mttd  | rca_service  | rca_correct |
|---|-------------------|----------|-------|--------------|-------------|
| 1 | payment_latency | Y | 1s | payment-svc | Y |
| 2 | payment_loss | Y | 1s | payment-svc | Y |
| 3 | inventory_kill | Y | 1s | inventory-svc | Y |
| 4 | gateway_cpu | Y | 1s | api-gateway | Y |
| 5 | payment_db_mem | Y | 1s | payment-db | Y |
| 6 | auth_clock | Y | 1s | auth-svc | Y |
| 7 | log_disk | Y | 1s | log-collector | Y |
| 8 | edge_partition | Y | 1s | frontend | Y |
| 9 | dns_slow | Y | 1s | dns-resolver | Y |
| 10 | checkout_retry_storm | Y | 1s | payment-svc | Y |

Gaps identified:
- none
```

## 3. Notable validation points

### DNS topology correction

`dns_slow` is the important RCA validation case. The raw pipeline RCA returns
`api-gateway`, but the runner normalizes that through
`configs/service_topology.yaml` and correctly scores the final root as
`dns-resolver`.

### Symptom-carrier defense

`checkout_retry_storm` does not score `checkout-svc` as root cause. The final
RCA is `payment-svc`, which satisfies the negative-test requirement.

### Meta-monitoring coverage

The previous blind spots on database memory pressure and log ingestion lag are
now detected through dedicated metrics and alert mappings, so experiments `5`
and `7` both pass.

## 4. Supporting runtime checks

- `scripts/start_stack.sh` starts the full Docker stack successfully
- `scripts/inject_fault.py` emits alert history and fault history correctly
- `scripts/capture_baseline.py` captured a smoke baseline into
  `runtime/baseline_smoke.json`
- `chaos_runner.py` completed the full suite and wrote `chaos_results.json`

## 5. Final conclusion

The repository now contains a working Docker-based D2 implementation with full
experiment coverage, topology-aware RCA normalization, and verified
end-to-end results at `10/10`.
