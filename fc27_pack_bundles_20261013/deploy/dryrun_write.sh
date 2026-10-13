#!/bin/sh
# 试运行（dry-run）演练：只出计划、绝不实际写。
# ★ Codex #7 加固：任一请求非 2xx 立即中止；写价前**再读一次持久化闸门**确认 dry_run=true。
set -e
API=http://127.0.0.1:8904
PY=/opt/python39/bin/python3

REV=$(curl -fsS "$API/api/state" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["revision"])')
echo "revision=$REV"

echo "== step1: write_enabled=true / write_dry_run=true / write_auto=false =="
curl -fsS -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d "{\"expected_revision\":$REV,\"settings\":{\"write_enabled\":true,\"write_dry_run\":true,\"write_auto\":false}}" \
  "$API/api/config"
echo

echo "== step2: 校验持久化闸门确为 dry_run=true =="
GATE=$(curl -fsS "$API/api/state" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["write"]["dry_run"])')
if [ "$GATE" != "True" ]; then
  echo "⛔ dry_run 闸门不是 True（实际 $GATE），中止——绝不触发写价" >&2
  exit 1
fi
echo "gate dry_run=$GATE OK"

echo "== step3: 触发写价（dry_run 生效 → 只出 planned） =="
curl -fsS -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d '{}' "$API/api/write-prices"
echo
sleep 40
echo "== step4: 写价日志尾部 =="
tail -c 2000 /opt/fc27-pack-bundles/data/write_log.json
