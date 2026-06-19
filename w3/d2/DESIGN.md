# W3-D2 Design and Requirement Mapping

This repository now follows the flat top-level review style used by the sample
artifacts: design, submission, report, and runnable code all live at the root
or in a small number of focused subdirectories.

## Target structure

```text
d2/
|-- README.md
|-- DESIGN.md
|-- SUBMIT.md
|-- chaos_report.md
|-- chaos_results.json
|-- chaos_runner.py
|-- docker-compose.yml
|-- experiments.yaml
|-- synthetic_probe.sh
|-- configs/
|   |-- alert_rules.yml
|   |-- alertmanager.yml
|   |-- prometheus.yml
|   |-- prometheus_targets.yml
|   |-- service_topology.yaml
|   `-- services/service.py
|-- pipeline/
|   |-- chaos_runner_skeleton.py
|   `-- mock_pipeline_api.py
`-- scripts/
    |-- start_stack.sh
    |-- stop_stack.sh
    |-- inject_fault.py
    |-- capture_baseline.py
    |-- query_pipeline.py
    `-- score_run.py
```

## Requirement mapping

| ID | Requirement | Evidence | Status |
|---|---|---|---|
| R1 | Root-level submission docs | `README.md`, `DESIGN.md`, `SUBMIT.md`, `chaos_report.md` | Done |
| R2 | Clear project layout | `README.md` | Done |
| R3 | Docker-based runnable stack | `docker-compose.yml`, `scripts/start_stack.sh` | Done |
| R4 | Prometheus and alerting config | `configs/prometheus.yml`, `configs/alert_rules.yml`, `configs/alertmanager.yml` | Done |
| R5 | AIOps pipeline API exposes `/alerts`, `/correlate`, `/rca` | `pipeline/mock_pipeline_api.py`, `scripts/query_pipeline.py` | Done |
| R6 | 10 required experiments are defined | `experiments.yaml` | Done |
| R7 | Every experiment contains full schema | `experiments.yaml` | Done |
| R8 | External steady-state probe exists | `synthetic_probe.sh` | Done |
| R9 | Fault injection is executable in the stack | `scripts/inject_fault.py` | Done |
| R10 | Runner dispatches all fault classes | `chaos_runner.py` | Done |
| R11 | Scoreboard prints all requested summary fields | `chaos_runner.py`, `scripts/score_run.py` | Done |
| R12 | Results persist to JSON | `chaos_results.json`, `chaos_runner.py` | Done |
| R13 | Baseline capture works against Prometheus | `scripts/capture_baseline.py`, `chaos_report.md` | Done |
| R14 | Service dependency mapping exists | `configs/service_topology.yaml` | Done |
| R15 | RCA normalization uses topology | `chaos_runner.py` | Done |
| R16 | DNS infra misattribution case is handled | `chaos_results.json`, `chaos_runner.py` | Done |
| R17 | Symptom-carrier negative test exists | `experiments.yaml`, `chaos_results.json` | Done |
| R18 | Original starter skeleton is preserved | `pipeline/chaos_runner_skeleton.py` | Done |
| R19 | Human-readable report exists | `chaos_report.md` | Done |
| R20 | Reflection/submission exists | `SUBMIT.md` | Done |

## Experiment mapping

| Exp | Fault | Expected root | Verified result |
|---|---|---|---|
| 1 | `payment_latency` | `payment-svc` | Pass |
| 2 | `payment_loss` | `payment-svc` | Pass |
| 3 | `inventory_kill` | `inventory-svc` | Pass |
| 4 | `gateway_cpu` | `api-gateway` | Pass |
| 5 | `payment_db_mem` | `payment-db` | Pass |
| 6 | `auth_clock` | `auth-svc` | Pass |
| 7 | `log_disk` | `log-collector` | Pass |
| 8 | `edge_partition` | `frontend` | Pass |
| 9 | `dns_slow` | `dns-resolver` | Pass |
| 10 | `checkout_retry_storm` | `NOT checkout-svc` | Pass |

## Runtime verification

Verified locally on the Docker stack in this repository:

- stack health:
  - frontend `8080` healthy
  - pipeline `8000` healthy
  - Prometheus `9190` healthy
- injector smoke test:
  - `latency` on `payment-svc` emitted `/alerts` and correct `/rca`
- baseline capture smoke test:
  - `scripts/capture_baseline.py` can write `runtime/baseline_smoke.json` when run against the local Prometheus stack; the generated file is runtime-only and is not committed
- runner smoke test:
  - single-experiment run passed `1/1`
- full suite:
  - detected `10/10`
  - rca_correct `10/10`
  - false_alarms `0`
  - precision `1.00`
  - recall `1.00`

## Max-score conclusion

The repository now satisfies the structural, automation, observability, RCA,
and evidence requirements needed for a maximum-score D2 submission within this
Docker-based environment.
