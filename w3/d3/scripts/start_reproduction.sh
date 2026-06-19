#!/usr/bin/env bash
set -euo pipefail
powershell.exe -NoProfile -Command '$root = "C:\Users\Admin\aiops-Thinh\w3\d3"; New-Item -ItemType Directory -Force -Path "$root\runtime" | Out-Null; Set-Content -Path "$root\runtime\events.jsonl" -Value ""; Set-Content -Path "$root\runtime\alerts.jsonl" -Value ""; Set-Content -Path "$root\runtime\rca.json" -Value "{}"; Set-Content -Path "$root\runtime\state.json" -Value "{""evil_regex_active"": false}"; Set-Content -Path "$root\runtime\metrics.json" -Value "{""requests"": 0, ""errors"": 0, ""last_latency_ms"": 0.0}"'
powershell.exe -NoProfile -Command 'Set-Location "C:\Users\Admin\aiops-Thinh\w3\d3\reproduction"; docker compose down --remove-orphans | Out-Null; docker compose up -d'
