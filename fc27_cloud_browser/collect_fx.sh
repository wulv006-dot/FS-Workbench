#!/bin/sh
set -eu
umask 077
evidence=/var/lib/fc27-cloud/evidence
state=/var/lib/fc27-cloud/state
mkdir -p -m 0700 "$evidence" "$state"
exec 9>"$state/fx.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
trace=$(mktemp "$evidence/fx-XXXXXXXX.tmp")
if timeout 50s docker exec -u fc27chrome \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  fc27-cloud-browser python3 /opt/fc27-collector/collect_fx_browser.py > "$trace"; then
  if python3 - "$trace" <<'PY'
import json,sys
x=json.load(open(sys.argv[1],encoding='utf-8'))
assert x.get('status')=='valid' and x.get('cny_per_usd') and x.get('published_at')
PY
  then
    mv "$trace" "${trace%.tmp}.json"
    printf '%s\n' '{"source":"BOC","status":"valid"}'
    exit 0
  fi
fi
mv "$trace" "${trace%.tmp}.failed.json"
printf '%s\n' '{"source":"BOC","status":"missing"}'
exit 1
