#!/bin/sh
set -eu
umask 077
run_id=${1:?run_id_required}
case "$run_id" in *[!a-fA-F0-9-]*|'') exit 2;; esac
quotes=/var/lib/fc27-cloud/quotes
previews=/var/lib/fc27-cloud/previews
state=/var/lib/fc27-cloud/state
mkdir -p -m 0700 "$previews" "$state"
chown root:11028 "$previews"
chmod 0750 "$previews"
exec 9>"$state/preview.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
trace=$(mktemp "$previews/.preview-XXXXXXXX.tmp")
if timeout 70s docker run --rm --network host --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  --mount type=bind,src="$quotes",dst=/run/quotes,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/preview_backend.py,dst=/opt/preview.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_logic.js,dst=/opt/repricing_logic.js,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_dom.js,dst=/opt/repricing_dom.js,readonly \
  --entrypoint python3 fc27-cloud-session:1 /opt/preview.py "$run_id" > "$trace"; then
  id=$(python3 - "$trace" <<'PY'
import json,re,sys
x=json.load(open(sys.argv[1],encoding='utf-8'))
value=x.get('preview_id','')
if x.get('status')!='review_only' or not re.fullmatch(r'[0-9a-f-]{36}',value):
    raise SystemExit(1)
print(value)
PY
  )
  if [ -n "$id" ]; then
    mv "$trace" "$previews/$id.json"
    chown root:11028 "$previews/$id.json"
    chmod 0640 "$previews/$id.json"
    printf '{"status":"review_only","preview_id":"%s","run_id":"%s"}\n' "$id" "$run_id"
    exit 0
  fi
fi
failed="${trace%.tmp}.failed.json"
mv "$trace" "$failed"
python3 - "$failed" <<'PY'
import json,re,sys
try:
    value=json.load(open(sys.argv[1],encoding='utf-8'))
    reason=str(value.get('reason','')).split(':',1)[0]
    if not re.fullmatch(r'[A-Za-z0-9_]{1,60}',reason):
        reason='browser_validation_failed'
except (OSError,ValueError):
    reason='browser_validation_failed'
print(json.dumps({'status':'NO_PREVIEW','reason':reason}))
PY
exit 1
