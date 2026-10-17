#!/bin/bash
# 探测器：查风控 → 解除则触发采集 → 新数据落库则自动跑验收
cd /opt/d4follow || exit 1
PY=/opt/d4follow/venv/bin/python3.9
R=$($PY _probe_once.py 2>&1 | tail -1)
curl -s -m 25 "http://127.0.0.1:8900/api/gold_cost?game=AION2" -o /tmp/gc_t.json 2>/dev/null
TS=$($PY -c "import json;print(json.load(open('/tmp/gc_t.json')).get('ts') or '')" 2>/dev/null)
echo "probe=$R ts=$TS"
if [ -n "$TS" ] && [ "$TS" != "2026-10-06T19:49:34" ]; then
  echo "=== NEWDATA $TS ==="
  sleep 25
  $PY /opt/d4follow/verify_aion2_after_1yi.py
  exit 0
fi
case "$R" in OK*)
  curl -s -m 20 -X POST http://127.0.0.1:8900/api/task -H 'Content-Type: application/json' -d '{"kind":"collect"}' >/dev/null 2>&1
  echo "TRIGGERED_COLLECT"
  ;;
esac
