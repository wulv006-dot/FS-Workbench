# Monitor health response compatibility

Owner/publisher: dot, for Wu Lv's 2026-10-20 request to repair the observed false alarm. One active target: `/opt/fc-ops-readonly-monitor/hooks.py`. No pricing, credentials, authorization, scheduling, notifications, service restarts, or Hermes automatic-publishing changes.

The active 8931 health response adds `active_customer_reports`. Comparing the entire JSON object with an old three-key literal causes `ValueError` and `exact_range_health_unavailable`, despite HTTP 200 and the expected service identity. The patch requires a JSON object, exact `service`, and boolean `ok is True` / `readonly is True`; additive fields are ignored. It preserves real failure alarms and does not claim business-query verification.

Baseline: active SHA256 b326c54808bacdda43d0f5b29e065d503256502d7765a0e75eee35b674223f0d, matching the gate-cycle-20261014 source. Candidate SHA256 792b84ee67f0441ba7da6e591d8029ef25eb3c41c6085d195c2dc1cf2856d753. Older ops/hooks files are historical and must not replace the current runtime.

Run: `python3 -B -m unittest discover -s releases/fc-coins/monitor-health-20261020/tests`. 20 focused tests passed locally. Existing pr-fast has one new affected group. These tests are isolated, not production acceptance.

The one-file adapter reuses the exact existing monitor publisher's baseline and metadata-preserving atomic swap functions; pins its observed SHA; acquires the existing collector lock without creating it; checks baseline before and under lock; backs up only this file and rolls it back on failure. No new persistent access is installed. First run publish.py without --apply. Applying is separately scoped to the user's repair request. Wait for the existing timer's next natural run and independently verify code hash, removal of the specific false alarm, original remaining warnings, and unchanged FC service state. No manual collector execution or notification is required.

Status: candidate tested; production acceptance pending. Hermes Bot Chat/admission lock report is a separate investigation.
