# README.md — MLOps Lifecycle: Anomaly Detection Pipeline

## Quick Start — Run Pipeline from Start to Finish

**Prerequisites:** Docker Compose running (for MLflow + PostgreSQL + Prometheus + Grafana), Python environment with `uv` installed, and dependencies: `mlflow`, `scikit-learn`, `pandas`, `evidently`, `fastapi`, `uvicorn`, `requests`, `prometheus_client`.

```bash
# 0. Start infrastructure stack
bash scripts/start_stack.sh

# 1. Install Python dependencies
uv pip install mlflow scikit-learn pandas evidently fastapi uvicorn requests prometheus_client

# 2. (Optional) Regenerate data files
uv run python data/generate_data.py

# 3. Train v1 model and register as @production
export MLFLOW_TRACKING_URI=http://localhost:5000
cd Thinh
uv run python pipeline.py --data ../data/baseline.csv

# 4. Start model serving (in a separate terminal)
uv run python serve.py --port 8000

# 5. Run drift detection (combined mode — detects both data drift + concept drift)
uv run python drift_detector.py \
    --reference ../data/baseline.csv \
    --current ../data/drifted.csv \
    --check-mode combined \
    --labeled-current ../data/drifted.csv \
    --model-uri models:/anomaly-detector@production \
    --log-mlflow

# 6. Run full retrain pipeline with holdout validation + post-deploy auto-rollback
uv run python retrain.py \
    --reference ../data/baseline.csv \
    --current ../data/drifted.csv \
    --holdout ../data/holdout.csv \
    --post-deploy-eval ../data/post_deploy_eval.csv \
    --auto-approve

# 7. Verify active version
curl http://localhost:8000/health/active-version

# 8. Test prediction
curl -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d '{"features": [[150.0, 1.2, 500.0]]}'

# 9. View Grafana dashboard
# Open http://localhost:3000 → Dashboard: "AIOps MLOps Lifecycle"

# 10. Stop infrastructure
bash scripts/stop_stack.sh
```

## Acceptance Criteria Verification

| Criterion | Command |
|-----------|---------|
| AC1-3: Core pipeline | Steps 3-4-6 above |
| AC4: Stress 1 — Combined drift detection | Step 5 (must print both `Drift score` and `Perf precision`) |
| AC5: Stress 2 — Holdout validation | Step 6 (must print `Holdout validation — v2 precision: X.XXXX  recall: X.XXXX`) |
| AC6: Stress 3 — Auto-rollback | Step 6 with `--post-deploy-eval` (check `outputs/audit_log.jsonl`) |
