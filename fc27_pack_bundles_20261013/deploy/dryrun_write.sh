#!/bin/sh
REV=$(curl -s http://127.0.0.1:8904/api/state | /opt/python39/bin/python3 -c 'import sys,json;print(json.load(sys.stdin)["revision"])')
echo "rev=$REV"
curl -s -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d "{\"expected_revision\":$REV,\"settings\":{\"write_enabled\":true,\"write_dry_run\":true,\"write_auto\":false}}" \
  http://127.0.0.1:8904/api/config
echo
curl -s -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
  -d '{}' http://127.0.0.1:8904/api/write-prices
echo
sleep 40
tail -c 2500 /opt/fc27-pack-bundles/data/write_log.json
