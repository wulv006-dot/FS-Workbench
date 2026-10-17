#!/bin/sh
API=http://127.0.0.1:8904
for T in "Premier League Player Bundle" "Barcelona Player Bundle" "Lyon Women Player Bundle" "LALIGA EA SPORTS Player Bundle"; do
  echo "=== $T ==="
  curl -s -X POST -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" \
    -d "{\"title\":\"$T\"}" "$API/api/discover-products" \
    | /opt/python39/bin/python3 -c 'import sys,json;d=json.load(sys.stdin);print("matched:",d.get("matched"),"| title:",d.get("matched_title"),"| unmatched:",d.get("unmatched"))'
done
