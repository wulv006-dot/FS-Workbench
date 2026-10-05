#!/bin/sh
set -eu
umask 077
site=${1:?site_required}
case "$site" in IGGM|U4GM|U7Buy) ;; *) exit 2 ;; esac
evidence=/var/lib/fc27-cloud/evidence
state=/var/lib/fc27-cloud/state
mkdir -p -m 0700 "$evidence" "$state"
exec 9>"$state/${site}.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
trace=$(mktemp "$evidence/${site}-XXXXXXXX.tmp")
if timeout 95s docker exec -u fc27chrome \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  fc27-cloud-browser python3 /opt/fc27-collector/collect_competitor_browser.py "$site" > "$trace"; then
  if python3 - "$trace" "$site" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1],encoding='utf-8'))
assert rows.get('source')==sys.argv[2] and rows.get('status')=='valid'
assert [x.get('platform') for x in rows.get('offers',[])]==['PS','XBOX','PC']
PY
  then
    mv "$trace" "${trace%.tmp}.json"
    printf '{"source":"%s","status":"valid","platforms":["PS","XBOX","PC"]}\n' "$site"
    exit 0
  fi
fi
mv "$trace" "${trace%.tmp}.failed.json"
printf '{"source":"%s","status":"missing"}\n' "$site"
exit 1
