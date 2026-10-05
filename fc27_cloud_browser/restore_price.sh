#!/bin/sh
set -eu
umask 077
request=${1:?request_json_required}
case "$request" in /var/lib/fc27-cloud/requests/*) ;; *) exit 2;; esac
[ -f "$request" ] && [ ! -L "$request" ] || exit 2
state=/var/lib/fc27-cloud/state
exec 9>"$state/price-writer.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
timeout 120s docker run --rm --network host --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  -e FC27_AUTOMATION_POLICY=/run/fc27/config/automation.json \
  --mount type=bind,src=/var/lib/fc27-cloud/config,dst=/run/fc27/config,readonly \
  --mount type=bind,src=/var/lib/fc27-cloud/executions,dst=/run/fc27/executions \
  --mount type=bind,src=/var/lib/fc27-cloud/restore-previews,dst=/run/fc27/restore-previews,readonly \
  --mount type=bind,src="$request",dst=/run/request.json,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/price_writer.py,dst=/opt/writer.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/automation_policy.py,dst=/opt/automation_policy.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/restore_price.py,dst=/opt/restore.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_logic.js,dst=/opt/repricing_logic.js,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_dom.js,dst=/opt/repricing_dom.js,readonly \
  --entrypoint python3 fc27-cloud-session:1 /opt/restore.py
