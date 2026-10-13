#!/bin/sh
# 正式写价流程：关试运行 → 执行写价 → 等待 → 回读日志。
# ★ Codex #7 加固：任一请求非 2xx 立即中止；写价前校验持久化闸门确为 dry_run=false
#   （避免"以为在试运行、其实已真写"或反之的静默错配）。
set -e
API=http://127.0.0.1:8904
PY=/opt/python39/bin/python3

REV=$(curl -fsS "$API/api/state" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["revision"])')
echo "revision=$REV"
echo "== step1: write_dry_run=false（真实写入） =="
curl -fsS -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d "{\"expected_revision\":$REV,\"settings\":{\"write_enabled\":true,\"write_dry_run\":false,\"write_auto\":false}}" \
  "$API/api/config"
echo

echo "== step2: 校验闸门已生效（enabled=true / dry_run=false） =="
GATE=$(curl -fsS "$API/api/state" | "$PY" -c 'import sys,json;w=json.load(sys.stdin)["write"];print("%s/%s"%(w["enabled"],w["dry_run"]))')
if [ "$GATE" != "True/False" ]; then
  echo "⛔ 闸门状态异常（实际 $GATE，期望 True/False），中止" >&2
  exit 1
fi
echo "gate=$GATE OK"

echo "== step3: 执行写价（真实写入） =="
curl -fsS -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d '{}' "$API/api/write-prices"
echo
echo "== step4: 等待完成（6 产品 × GET+POST+回读 ≈ 60-90s） =="
sleep 80
echo "== step5: 写价日志尾部 =="
tail -c 3000 /opt/fc27-pack-bundles/data/write_log.json
echo
echo "== step6: 快照文件 =="
ls /opt/fc27-pack-bundles/data/before/ 2>/dev/null
