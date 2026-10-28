#!/bin/sh
set -eu
umask 077
request=${1:?request_json_required}
case "$request" in /var/lib/fc27-cloud/requests/*) ;; *) exit 2;; esac
[ -f "$request" ] && [ ! -L "$request" ] || exit 2
state=/var/lib/fc27-cloud/state
exec 9>"$state/price-writer.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
if guard_result=$(timeout 45s /opt/python39/bin/python3 -B /opt/fc27-cloud-browser/pricing_sources.py "$request"); then :
else
  printf '%s\n' "$guard_result" | /opt/python39/bin/python3 -B -c 'import json,sys; sys.path.insert(0,"/opt/fc27-cloud-browser"); from fc_pricing_v3.dispatch import prewrite_refusal; print(json.dumps(prewrite_refusal(sys.stdin.read())))'
  exit 1
fi
timeout 120s docker run --rm --init --memory 2g --memory-swap 2g --env PYTHONPATH=/opt:/opt/fs-order-session --mount type=bind,src=/opt/fc27-cloud-browser/isolated_backend.py,dst=/opt/isolated_backend.py,readonly --network host --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --mount type=bind,src=/opt/fc27-cloud-browser/fc_shared_admin.py,dst=/usr/local/bin/p2pah_session_service.py,readonly \
  -e FS_ADMIN_API_BASE=http://127.0.0.1:8912 \
  --mount type=bind,src=/opt/fs-order-session,dst=/opt/fs-order-session,readonly \
  --mount type=bind,src=/run/fs-order-session,dst=/run/fs-order-session,readonly \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  -e FC27_AUTOMATION_POLICY=/run/fc27/config/automation.json \
  --mount type=bind,src=/var/lib/fc27-cloud/config,dst=/run/fc27/config,readonly \
  --mount type=bind,src=/var/lib/fc27-cloud/executions,dst=/run/fc27/executions \
  --mount type=bind,src=/var/lib/fc27-cloud/restore-previews,dst=/run/fc27/restore-previews,readonly \
  --mount type=bind,src=/var/lib/fc27-cloud/quotes,dst=/run/fc27/quotes,readonly \
  --mount type=bind,src="$request",dst=/run/request.json,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/price_writer.py,dst=/opt/writer.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/automation_policy.py,dst=/opt/automation_policy.py,readonly \
  -e FC27_V3_ROOT=/run/fc27 \
  --mount type=bind,src=/opt/fc27-cloud-browser/fc_pricing_v3,dst=/opt/fc_pricing_v3,readonly \
  --mount type=bind,src=/var/lib/fc27-cloud/v3,dst=/run/fc27/v3,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/pricing_v2.py,dst=/opt/pricing_v2.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/restore_price.py,dst=/opt/restore.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/fc27_quote_engine.py,dst=/opt/fc27_quote_engine.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/coin_all_sync_job.py,dst=/opt/coin_all_sync_job.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_logic.js,dst=/opt/repricing_logic.js,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_dom.js,dst=/opt/repricing_dom.js,readonly \
  --entrypoint python3 fc27-cloud-session:1 /opt/restore.py
