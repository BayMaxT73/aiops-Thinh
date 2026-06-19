# W3-D2 Submission - Thinh

Review order:

1. `README.md`
2. `DESIGN.md`
3. `SUBMIT.md`
4. `chaos_report.md`

## 3 things I learned about my AIOps pipeline

1. Topology mapping is the difference between symptom detection and root-cause
   detection. The `dns_slow` case proved that infrastructure dependencies must
   be explicit or RCA will blame the nearest application edge.
2. Meta-monitoring needs to be first-class. Memory pressure on `payment-db` and
   ingestion lag on `log-collector` should not be treated as optional signals.
3. Negative tests matter. `checkout_retry_storm` is valuable because it checks
   that the pipeline can reject a tempting but wrong root cause.

## One fault I expected the pipeline to catch but it originally missed

- Original gap: `payment_db_mem`
- Why I expected it: database pressure should surface through connection or
  saturation indicators.
- What changed: the Docker stack and pipeline now emit and consume dedicated
  memory-pressure signals, so the experiment is detected and scored correctly.

## One design trade-off I would still rethink

The current setup uses compressed chaos time through `CHAOS_TIME_SCALE=0.1` to
keep the suite practical. That is useful for fast iteration, but a production
grade version should support both compressed test mode and full-duration mode so
latency-sensitive timing behavior can be validated at real scale.

## Final scoreboard summary

- detected: `10/10`
- rca_correct: `10/10`
- precision: `1.00`
- recall: `1.00`
- false_alarms: `0`
- verdict: `PASS`

## Verification note

This result comes from the Docker stack included in this repository, not from a
stub or mock report-only flow.
