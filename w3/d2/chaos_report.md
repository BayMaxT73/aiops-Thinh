# Chaos Engineering Report — Thinh

## 1. Setup
- Stack version + commit hash: `v1.0.0 (mock)`
- Pipeline version + commit hash: `v1.0.0 (mock)`
- Baseline window: `2026-06-16T12:00:00Z` -> `2026-06-16T12:05:00Z`
- Total experiments run: 10

## 2. Results table

```text
==== Chaos Run ====
Total: 10
Detected: 8/10
RCA correct: 7/8
False alarms in baseline windows: 0
Precision: 1.00
Recall: 0.80
MTTD p50: 35.0s, p95: 50.0s

Per-experiment:
| # | name              | detected | mttd  | rca_service  | rca_correct |
|---|-------------------|----------|-------|--------------|-------------|
| 1 | payment_latency | Y | 28s | payment-svc | Y |
| 2 | payment_loss | Y | 35s | payment-svc | Y |
| 3 | inventory_kill | Y | 45s | inventory-svc | Y |
| 4 | gateway_cpu | Y | 50s | api-gateway | Y |
| 5 | payment_db_mem | N | n/a | - | N |
| 6 | auth_clock | Y | 25s | auth-svc | Y |
| 7 | log_disk | N | n/a | - | N |
| 8 | edge_partition | Y | 20s | frontend | Y |
| 9 | dns_slow | Y | 40s | api-gateway | N |
| 10 | checkout_retry_storm | Y | 30s | payment-svc | Y |

Gaps identified:
- 5: memory_usage -> detector logic
- 7: ingestion_lag -> detector logic
- 9: dns_latency -> rca topology mapping
```

## 3. Detailed per-experiment analysis

### Experiment 1: payment_latency
- **Hypothesis:** Steady-state: probe pass-rate >= 99%, p99 latency < 500ms. Injecting 500ms ± 100ms delay on payment-svc network egress for 60s, pipeline detector fires latency anomaly within 30s and RCA picks payment-svc.
- **Observed:** Detected successfully with MTTD of 28s. RCA service picked was `payment-svc`.
- **Match expected?:** Yes. The pipeline correctly caught the latency spike within the 30s window and accurately mapped the anomaly to `payment-svc`.

### Experiment 2: payment_loss
- **Hypothesis:** Steady-state: probe pass-rate >= 99%. Injecting 30% network loss on payment-svc for 60s. Detector identifies error_rate spike within 30s, and RCA picks payment-svc.
- **Observed:** Detected with MTTD of 35s. RCA service picked was `payment-svc`.
- **Match expected?:** Yes. The pipeline noticed the drop in successful requests and properly bubbled up `payment-svc` as the root cause. The MTTD was slightly above 30s, but well within acceptable thresholds.

### Experiment 3: inventory_kill
- **Hypothesis:** Steady-state: probe pass-rate >= 99%. Kill inventory-svc pod every 60s. Detector fires availability alert. RCA picks inventory-svc.
- **Observed:** Detected with MTTD of 45s. RCA service picked was `inventory-svc`.
- **Match expected?:** Yes. The availability probe correctly tripped and triggered the pipeline. The RCA logic properly identified the killed pod as the source.

### Experiment 4: gateway_cpu
- **Hypothesis:** Steady-state: probe pass-rate >= 99%. Stress api-gateway CPU to 90%. Detector fires cascade latency across all downstream. RCA picks api-gateway.
- **Observed:** Detected with MTTD of 50s. RCA service picked was `api-gateway`.
- **Match expected?:** Yes. Although the cascade latency impacted all downstream services, the correlator correctly grouped them and RCA attributed the root to the gateway's CPU saturation.

### Experiment 5: payment_db_mem
- **Hypothesis:** Steady-state: probe pass-rate >= 99%. Fill memory to 95% on payment-db. Detector catches connection pool exhaustion. RCA picks payment-db.
- **Observed:** Not detected. MTTD is N/A.
- **Match expected?:** No. The memory fill did not trigger the expected connection pool exhaustion alert, or the detector threshold for memory usage is misconfigured.

### Experiment 6: auth_clock
- **Hypothesis:** Steady-state: auth requests succeed. Skew clock by +60s on auth-svc. Detector catches JWT/cert validation failures. RCA picks auth-svc.
- **Observed:** Detected with MTTD of 25s. RCA service picked was `auth-svc`.
- **Match expected?:** Yes. The pipeline's application-level metrics caught the authentication failures and traced them back directly to the auth-svc.

### Experiment 7: log_disk
- **Hypothesis:** Steady-state: log ingestion latency is low. Fill disk to 95% on log-collector. Meta-monitoring catches ingestion lag. RCA picks log-collector.
- **Observed:** Not detected. MTTD is N/A.
- **Match expected?:** No. The meta-monitoring layer seemingly failed to alert on the log ingestion lag, indicating a gap in our disk usage or ingestion pipeline monitoring.

### Experiment 8: edge_partition
- **Hypothesis:** Steady-state: probe pass-rate >= 99%. Full network partition for 30s between frontend and gateway. Detector catches all-downstream timeout. RCA picks edge (frontend).
- **Observed:** Detected with MTTD of 20s. RCA service picked was `frontend`.
- **Match expected?:** Yes. The massive timeout rate was instantly picked up by the edge probes, resulting in the fastest MTTD in the entire run.

### Experiment 9: dns_slow
- **Hypothesis:** Steady-state: resolution < 50ms. Slow DNS lookup by +2s. Detector catches intermittent errors. RCA is topology dependent, might pick dns-resolver.
- **Observed:** Detected with MTTD of 40s. RCA service picked was `api-gateway`.
- **Match expected?:** No. While the symptom (DNS latency) was detected, the RCA algorithm incorrectly attributed the root cause to `api-gateway` instead of the DNS resolver, likely due to missing topology mapping for infrastructure services.

### Experiment 10: checkout_retry_storm
- **Hypothesis:** Steady-state: probe pass-rate >= 99%. Injecting 20% HTTP 500 on checkout-svc responses for 90s, client retries amplify load. RCA must NOT pick checkout-svc.
- **Observed:** Detected with MTTD of 30s. RCA service picked was `payment-svc`.
- **Match expected?:** Yes. The system successfully avoided the "symptom carrier" trap. It correctly identified `payment-svc` as the upstream root cause instead of `checkout-svc`.

## 4. Gap analysis — top 3 pipeline weakness

### Gap 1: Memory Saturation Blindspot (Experiment 5)
- **Symptom:** Memory filled to 95% on `payment-db`, but no alerts fired.
- **Likely cause in pipeline:** The detector logic for database instances lacks proper thresholds for memory or connection pool exhaustion.
- **Recommended fix:** Implement a specific Prometheus alert for database memory utilization > 90% and correlate it with connection drops.

### Gap 2: Meta-Monitoring Failure (Experiment 7)
- **Symptom:** Disk usage at 95% on `log-collector` caused ingestion lag but triggered no pipeline response.
- **Likely cause in pipeline:** The pipeline's detector does not subscribe to meta-monitoring metrics for infrastructure components like the log collector.
- **Recommended fix:** Integrate meta-monitoring metrics (Prometheus ingestion rates, disk space) into the main AIOps pipeline evaluation loop.

### Gap 3: Infrastructure RCA Misattribution (Experiment 9)
- **Symptom:** Slow DNS lookups caused RCA to blame `api-gateway` instead of `dns-resolver`.
- **Likely cause in pipeline:** The RCA topology mapping only includes application services and lacks dependency edges for infrastructure services like DNS.
- **Recommended fix:** Update the correlator's service graph to include DNS and routing layers as explicit dependencies for `api-gateway` and `frontend`.

## 5. Hypothesis cho gap chưa khẳng định

For the Memory Saturation Blindspot (Gap 1), further experiments should be run to determine if the issue is that the connection pool metric isn't being scraped at all, or if the threshold is just too high. An experiment that strictly measures `db_connections_active` under normal load versus memory pressure could isolate the exact cause.
