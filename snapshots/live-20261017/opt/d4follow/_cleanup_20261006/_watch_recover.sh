#!/bin/bash
OUT=/opt/d4follow/_recover_watch.txt
: > $OUT
for i in $(seq 1 40); do
  R=$(cd /opt/d4follow && ./venv/bin/python3.9 /opt/d4follow/_probe_once.py 2>&1 | tail -1)
  echo "[$(date +%H:%M:%S)] i=$i $R" >> $OUT
  case "$R" in OK*)
     echo "=== 风控已解除（$R），触发采集 ===" >> $OUT
     curl -s -m 20 -X POST http://127.0.0.1:8900/api/task \
       -H 'Content-Type: application/json' -d '{"kind":"collect"}' >> $OUT 2>&1
     echo >> $OUT
     exit 0;;
  esac
  sleep 180
done
echo "=== 超时未恢复 ===" >> $OUT
