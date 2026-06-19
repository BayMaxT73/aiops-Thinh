# SUBMIT.md — Kết quả chạy 3 chaos scenarios

## Thông tin

- Decision engine: Rule-based (`runbook_map` trong `config.yaml`)
- Python: 3.12
- Docker Compose: v2

---

## Scenario 1 — Action thành công (InstanceDown trên payment-svc)

**Inject:** Stop container payment-svc, Prometheus detect InstanceDown, orchestrator restart và verify pass.

**Log orchestrator (thực tế):**
```json
{"ts": "2026-06-18T09:18:41.358681+00:00", "level": "INFO", "event_type": "ORCHESTRATOR_START", "config": "config.yaml", "dry_run": false, "poll_interval_s": 15}
{"ts": "2026-06-18T09:20:11.929118+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "InstanceDown", "service": "payment-svc", "severity": "critical"}
{"ts": "2026-06-18T09:20:11.929118+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "InstanceDown", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T09:20:11.929118+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "payment-svc"}
{"ts": "2026-06-18T09:20:11.929118+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": true}
{"ts": "2026-06-18T09:20:12.084508+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[DRY-RUN] would execute: docker restart ronki-payment-svc", "stderr": ""}
{"ts": "2026-06-18T09:20:12.084508+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-18T09:20:12.085042+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": false}
{"ts": "2026-06-18T09:20:18.806493+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-payment-svc...\nronki-payment-svc\n[restart_service] Waiting 5s for ronki-payment-svc to come up...\n[restart_service] ronki-payment-svc is running.", "stderr": ""}
{"ts": "2026-06-18T09:20:18.806493+00:00", "level": "INFO", "event_type": "ACTION_EXECUTED", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-18T09:20:18.806493+00:00", "level": "INFO", "event_type": "VERIFY_START", "service": "payment-svc", "timeout_s": 60}
{"ts": "2026-06-18T09:20:18.833919+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 1, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T09:20:28.849277+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 2, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T09:20:38.884737+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 3, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T09:20:48.904891+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 4, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T09:20:48.904891+00:00", "level": "INFO", "event_type": "VERIFY_PASS", "service": "payment-svc", "samples": 4}
{"ts": "2026-06-18T09:20:48.904891+00:00", "level": "INFO", "event_type": "ACTION_SUCCESS", "alertname": "InstanceDown", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
```

**Kết quả:** PASS. Orchestrator detect InstanceDown, dry-run pass, restart container thành công, verify `up=1.0` qua 3 sample liên tiếp → ACTION_SUCCESS.

---

## Scenario 2 — Action fail → rollback (checkout-svc, threshold thấp)

**Thiết lập:** Set `up_required: 2` trong `baseline.json` để verify luôn fail (up chỉ trả về 1.0, không bao giờ đạt 2), kiểm tra rollback logic.

**Inject:** `docker stop ronki-checkout-svc`

**Log orchestrator (thực tế):**
```json
{"ts": "2026-06-18T09:47:32.237242+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "InstanceDown", "service": "checkout-svc", "severity": "critical"}
{"ts": "2026-06-18T09:47:32.237242+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "InstanceDown", "service": "checkout-svc", "runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T09:47:32.237242+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "checkout-svc"}
{"ts": "2026-06-18T09:47:32.357545+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/restart_service.sh", "service": "checkout-svc"}
{"ts": "2026-06-18T09:47:37.900547+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-checkout-svc...\nronki-checkout-svc\n[restart_service] Waiting 5s for ronki-checkout-svc to come up...\n[restart_service] ronki-checkout-svc is running.", "stderr": ""}
{"ts": "2026-06-18T09:47:37.900547+00:00", "level": "INFO", "event_type": "ACTION_EXECUTED", "runbook": "runbooks/restart_service.sh", "service": "checkout-svc"}
{"ts": "2026-06-18T09:47:37.907172+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "sample": 1, "latency_p99_ms": null, "up": 0.0, "latency_ok": false, "up_ok": false}
{"ts": "2026-06-18T09:47:47.935968+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "sample": 2, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": false}
{"ts": "2026-06-18T09:47:57.961474+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "sample": 3, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": false}
{"ts": "2026-06-18T09:48:07.981553+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "sample": 4, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": false}
{"ts": "2026-06-18T09:48:18.006079+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "sample": 5, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": false}
{"ts": "2026-06-18T09:48:28.047839+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "sample": 6, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": false}
{"ts": "2026-06-18T09:48:38.049663+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "checkout-svc", "samples": 6}
{"ts": "2026-06-18T09:48:38.049663+00:00", "level": "WARNING", "event_type": "ROLLBACK_TRIGGERED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T09:48:44.942588+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-checkout-svc...\nronki-checkout-svc\n[restart_service] Waiting 5s for ronki-checkout-svc to come up...\n[restart_service] ronki-checkout-svc is running.", "stderr": ""}
{"ts": "2026-06-18T09:48:44.943171+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
```

**Kết quả:** PASS. Verify fail sau 6 sample (60s timeout), orchestrator tự động trigger rollback không cần can thiệp tay.

---

## Scenario 3 — Circuit breaker (3 consecutive failures)

**Thiết lập:** Giữ `up_required: 2`. Để orchestrator chạy liên tục — Alertmanager re-fire alert mỗi 2 phút, orchestrator tự đếm 3 lần fail → CIRCUIT_BREAKER_HALT.

**Log orchestrator (thực tế):**
```json
{"ts": "2026-06-18T14:22:52.303227+00:00", "level": "INFO", "event_type": "VERIFY_START", "service": "checkout-svc", "timeout_s": 60}
{"ts": "2026-06-18T14:23:52.561029+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "checkout-svc", "samples": 6}
{"ts": "2026-06-18T14:23:52.561029+00:00", "level": "WARNING", "event_type": "ROLLBACK_TRIGGERED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T14:23:59.660575+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}

{"ts": "2026-06-18T14:26:52.049310+00:00", "level": "INFO", "event_type": "ACTION_EXECUTED", "runbook": "runbooks/restart_service.sh", "service": "checkout-svc"}
{"ts": "2026-06-18T14:27:52.255727+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "checkout-svc", "samples": 6}
{"ts": "2026-06-18T14:27:52.255727+00:00", "level": "WARNING", "event_type": "ROLLBACK_TRIGGERED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T14:27:59.217739+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T14:27:59.217739+00:00", "level": "ERROR", "event_type": "CIRCUIT_BREAKER_HALT", "consecutive_failures": 3, "threshold": 3, "message": "Automation halted. Manual intervention required."}

{"ts": "2026-06-18T14:28:14.221190+00:00", "level": "ERROR", "event_type": "CIRCUIT_BREAKER_HALT", "message": "Circuit open — polling suspended."}
{"ts": "2026-06-18T14:28:29.221661+00:00", "level": "ERROR", "event_type": "CIRCUIT_BREAKER_HALT", "message": "Circuit open — polling suspended."}
{"ts": "2026-06-18T14:28:44.222427+00:00", "level": "ERROR", "event_type": "CIRCUIT_BREAKER_HALT", "message": "Circuit open — polling suspended."}
```

**Kết quả:** PASS. Sau 3 lần VERIFY_FAIL + ROLLBACK liên tiếp, orchestrator log `CIRCUIT_BREAKER_HALT consecutive_failures=3` và dừng toàn bộ automation. Các poll tiếp theo chỉ log `Circuit open — polling suspended.`

---

## Điều học được

Checkpoint khó nhất là **Verify** — verify phải check đúng metric theo từng loại alert. Ban đầu code check cả `latency_ok AND up_ok` cho mọi alert, dẫn đến `InstanceDown` luôn verify fail vì không có histogram data sau restart. Sau khi sửa `verify.py` để `InstanceDown` chỉ check `up_ok`, hệ thống hoạt động đúng.

Windows không hỗ trợ `nsenter` nên không dùng được `inject_fault.sh latency` — phải inject bằng cách recreate container với `BASE_LATENCY_MS=600`. Ngoài ra `closed_loop.py` dùng `/bin/bash` (Linux path) phải đổi thành `bash` để chạy trên Windows.