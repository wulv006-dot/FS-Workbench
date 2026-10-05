#!/bin/sh
set -eu
umask 077
request=${1:?request_json_required}
case "$request" in /var/lib/fc27-cloud/requests/*) ;; *) exit 2;; esac
[ -f "$request" ] && [ ! -L "$request" ] || exit 2
state=/var/lib/fc27-cloud/state
exec 9>"$state/price-writer.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
exec_dir=/var/lib/fc27-cloud/executions
install -d -o root -g 11028 -m 2770 "$exec_dir"
all_dir=/var/lib/fc27-cloud/all-coin-sync
install -d -o root -g 11028 -m 2770 "$all_dir"
timeout 120s docker run --rm --network host --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  -e FC27_AUTOMATION_POLICY=/run/fc27/config/automation.json \
  --mount type=bind,src=/var/lib/fc27-cloud/config,dst=/run/fc27/config,readonly \
  --mount type=bind,src=/etc/fc27-cloud/fc27.env,dst=/run/secrets/fc27.env,readonly \
  --mount type=bind,src="$all_dir",dst=/run/fc27/all-coin-sync \
  --mount type=bind,src=/var/lib/fc27-cloud/runs,dst=/run/fc27/runs,readonly \
  --mount type=bind,src=/var/lib/fc27-cloud/quotes,dst=/run/fc27/quotes,readonly \
  --mount type=bind,src=/var/lib/fc27-cloud/previews,dst=/run/fc27/previews,readonly \
  --mount type=bind,src="$exec_dir",dst=/run/fc27/executions \
  --mount type=bind,src="$request",dst=/run/request.json,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/price_writer.py,dst=/opt/writer.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/coin_all_sync_job.py,dst=/opt/coin_all_sync_job.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/fc27_quote_engine.py,dst=/opt/fc27_quote_engine.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/automation_policy.py,dst=/opt/automation_policy.py,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_logic.js,dst=/opt/repricing_logic.js,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/repricing_dom.js,dst=/opt/repricing_dom.js,readonly \
  --entrypoint python3 fc27-cloud-session:1 /opt/writer.py
