# W3-D2 Submission — Thinh

## 3 thứ tôi học được về AIOps pipeline của mình
1. **Topology Mapping is Crucial**: Without explicit dependency mapping for infrastructure components (like the DNS resolver), the RCA logic will misattribute errors to edge services like the API gateway.
2. **Meta-monitoring is a Requirement, not a Luxury**: Application metrics are insufficient. Outages caused by underlying host issues like disk-fill on log collectors won't be caught unless system metrics are directly integrated into the AIOps pipeline.
3. **Graceful Handling of Symptom Carriers**: The pipeline's ability to differentiate between a service experiencing a retry storm (checkout-svc) versus the actual broken upstream service (payment-svc) proved that proper correlation windows are effective at reducing noise.

## 1 fault mà tôi mong pipeline catch nhưng nó miss
- **Experiment**: 5. payment_db_mem (Memory fill 95% on payment-db)
- **Why I expected detection**: I expected the database to exhaust its connection pool, which should have been immediately caught by our database connection monitoring metrics.
- **Why pipeline missed (hypothesis)**: The detector thresholds might be statically set too high, or the specific memory utilization metric for the database instances isn't properly weighted in the anomaly detection engine.

## 1 trade-off trong design pipeline mà tôi muốn rethink
Currently, the pipeline uses a fixed 120s cooldown and static evaluation windows. This design guarantees simplicity but limits agility. I would like to rethink this trade-off by introducing dynamic correlation windows that adjust based on the severity and velocity of incoming alerts, allowing us to catch fast-moving cascades quicker while still buffering slow-burn memory leaks.

## Scoreboard summary
- detected: 8/10
- rca_correct: 7/8
- mttd_p50: 35.0s
- false_alarms: 0
- verdict: PASS
