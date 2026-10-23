#!/bin/sh
set -eu
umask 077

state=/var/lib/fc27-cloud/state
evidence=/var/lib/fc27-cloud/evidence
mkdir -p -m 0700 "$state" "$evidence"
exec 9>"$state/lootbar.lock"
if ! flock -n 9; then
  printf '%s\n' '{"status":"busy","read_only":true}'
  exit 75
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
trace=$(mktemp "$evidence/lootbar-${stamp}-XXXXXX.tmp")
if ! timeout 90s docker exec -u fc27chrome \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  fc27-cloud-browser python3 /opt/fc27-collector/lootbar_server_collector.py > "$trace"; then
  mv "$trace" "${trace%.tmp}.failed.jsonl"
  printf '%s\n' '{"status":"failed","read_only":true}'
  exit 1
fi

if summary=$(python3 - "$trace" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    events = [json.loads(line) for line in stream if line.strip()]
last = events[-1] if events else {}
if (last.get("stage") != "complete" or last.get("read_only") is not True
        or set((last.get("offers") or {}).keys()) != {"PS", "XBOX", "PC"}
        or not any(e.get("stage") == "ps_restored" for e in events)):
    raise SystemExit(1)
print(json.dumps({"status": "valid", "read_only": True,
                  "checked_at": last.get("checked_at"),
                  "platforms": ["PS", "XBOX", "PC"], "ps_restored": True}))
PY
); then
  mv "$trace" "${trace%.tmp}.jsonl"
  printf '%s\n' "$summary"
else
  mv "$trace" "${trace%.tmp}.failed.jsonl"
  printf '%s\n' '{"status":"invalid","read_only":true}'
  exit 1
fi
