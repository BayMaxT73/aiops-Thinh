#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p runtime/faults
: > runtime/alert_history.jsonl
: > runtime/fault_history.jsonl

docker compose down --remove-orphans >/dev/null 2>&1 || true
docker compose up -d

echo "Waiting for frontend..."
until curl -sf http://localhost:8080/health >/dev/null; do sleep 2; done

echo "Waiting for pipeline..."
until curl -sf http://localhost:8000/health >/dev/null; do sleep 2; done

echo "Waiting for Prometheus..."
until curl -sf http://localhost:9190/-/healthy >/dev/null; do sleep 2; done

echo "Stack ready."
