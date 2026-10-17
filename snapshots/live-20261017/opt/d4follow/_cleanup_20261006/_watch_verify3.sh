#!/bin/bash
OUT=/opt/d4follow/_verify_result3.txt
: > $OUT
B=""
for i in $(seq 1 70); do
  TS=$(curl -s -m 30 "http://127.0.0.1:8900/api/gold_cost?game=AION2" | python3 -c "import sys,json;print(json.load(sys.stdin).get('ts') or '')" 2>/dev/null)
  if [ -z "$B" ]; then B="$TS"; echo "[$(date +%H:%M:%S)] baseline ts=$B" >> $OUT; fi
  echo "[$(date +%H:%M:%S)] i=$i ts=$TS" >> $OUT
  if [ -n "$TS" ] && [ "$TS" != "$B" ]; then
    echo "=== 新数据已落库 ($TS)，等 25s 让派单跑完 ===" >> $OUT
    sleep 25
    /opt/d4follow/venv/bin/python3.9 /opt/d4follow/verify_aion2_after_1yi.py >> $OUT 2>&1
    echo "=== DONE ===" >> $OUT
    exit 0
  fi
  sleep 45
done
echo "=== TIMEOUT ===" >> $OUT
