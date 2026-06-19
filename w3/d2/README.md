# W3-D2 Chaos Engineering

This repository now ships a working Docker-based D2 stack:

- 11 mock application and infrastructure services
- Prometheus on `http://localhost:9190`
- Alertmanager on `http://localhost:9193`
- AIOps pipeline API on `http://localhost:8000`
- chaos runner, baseline capture, scoreboard, report, and submission artifacts

## Repository layout

```text
README.md                         this file
DESIGN.md                         requirement map and verification status
SUBMIT.md                         reflection and final score summary
chaos_report.md                   detailed run report
chaos_results.json                latest run output
chaos_runner.py                   chaos suite runner
docker-compose.yml                full D2 Docker stack
experiments.yaml                  10 completed chaos experiments
experiments_template.yaml         starter template
synthetic_probe.sh                external steady-state probe
run_scoreboard.py                 offline scoreboard entry point
configs/
|-- alert_rules.yml               Prometheus alert rules
|-- alertmanager.yml              Alertmanager routing
|-- prometheus.yml                Prometheus scrape config
|-- prometheus_targets.yml        target inventory for the stack
|-- service_topology.yaml         dependency graph for RCA normalization
`-- services/service.py           generic mock service implementation
pipeline/
|-- chaos_runner_skeleton.py      original starter skeleton
`-- mock_pipeline_api.py          Dockerized pipeline API
scripts/
|-- start_stack.sh                bring up the D2 stack
|-- stop_stack.sh                 tear down the D2 stack
|-- inject_fault.py               Docker-backed fault injector
|-- capture_baseline.py           Prometheus baseline capture
|-- query_pipeline.py             inspect /alerts, /correlate, /rca
`-- score_run.py                  render scoreboard from saved results
runtime/
`-- ...                           generated fault and alert history
```

## Start and stop

```bash
bash scripts/start_stack.sh
bash scripts/stop_stack.sh
```

Health endpoints:

- frontend: `http://localhost:8080/health`
- pipeline: `http://localhost:8000/health`
- Prometheus: `http://localhost:9190/-/healthy`
- Alertmanager: `http://localhost:9193/-/healthy`

## Run the suite

```bash
python scripts/capture_baseline.py --duration 60 --out runtime/baseline_smoke.json
python chaos_runner.py --out chaos_results.json
python run_scoreboard.py
```

The injector runs on a compressed time scale by default via
`CHAOS_TIME_SCALE=0.1`, so the 10-experiment suite finishes in about 2 minutes
instead of more than 20.

## Current verified result

Latest end-to-end Docker run:

- detected: `10/10`
- rca_correct: `10/10`
- precision: `1.00`
- recall: `1.00`
- false_alarms: `0`
- verdict: `PASS (max-score target met)`

## Review order

1. `README.md`
2. `DESIGN.md`
3. `SUBMIT.md`
4. `chaos_report.md`
