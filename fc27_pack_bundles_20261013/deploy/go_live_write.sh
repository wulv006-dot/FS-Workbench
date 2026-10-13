#!/bin/sh
# 正式写价流程：关试运行 → 执行写价 → 等待 → 回读日志
REV=$(curl -s http://127.0.0.1:8904/api/state | /opt/python39/bin/python3 -c 'import sys,json;print(json.load(sys.stdin)["revision"])')
echo "revision=$REV"
echo "== step1: write_dry_run=false =="
curl -s -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d "{\"expected_revision\":$REV,\"settings\":{\"write_enabled\":true,\"write_dry_run\":false,\"write_auto\":false}}" \
  http://127.0.0.1:8904/api/config
echo
echo "== step2: 执行写价（真实写入） =="
curl -s -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d '{}' http://127.0.0.1:8904/api/write-prices
echo
echo "== step3: 等待完成（6 产品 × GET+POST+回读 ≈ 60-90s） =="
sleep 80
echo "== step4: 写价日志尾部 =="
tail -c 3000 /opt/fc27-pack-bundles/data/write_log.json
echo
echo "== step5: 快照文件 =="
ls /opt/fc27-pack-bundles/data/before/ 2>/dev/null
