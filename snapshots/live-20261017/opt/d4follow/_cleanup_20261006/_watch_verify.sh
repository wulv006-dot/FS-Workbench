#!/bin/bash
OLD=2026-10-06T19:11:58
OUT=/opt/d4follow/_verify_result.txt
: > $OUT
for i in $(seq 1 45); do
  TS=$(curl -s -m 30 "http://127.0.0.1:8900/api/gold_cost?game=AION2" | python3 -c "import sys,json;print(json.load(sys.stdin).get('ts') or '')" 2>/dev/null)
  echo "[$(date +%H:%M:%S)] i=$i ts=$TS" >> $OUT
  if [ -n "$TS" ] && [ "$TS" != "$OLD" ]; then
    echo "=== 新数据已落库，开始验收 ===" >> $OUT
    sleep 5
    /opt/d4follow/venv/bin/python3.9 /opt/d4follow/verify_aion2_after_1yi.py >> $OUT 2>&1
    echo "=== DONE ===" >> $OUT
    exit 0
  fi
  sleep 40
done
echo "=== TIMEOUT ===" >> $OUT
