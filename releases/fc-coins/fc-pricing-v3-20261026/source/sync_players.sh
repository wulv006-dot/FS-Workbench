#!/bin/sh
set -eu
umask 077
request=${1:?request_json_required}
case "$request" in /var/lib/fc27-cloud/requests/*) ;; *) exit 2;; esac
[ -f "$request" ] && [ ! -L "$request" ] || exit 2
job_id=$(python3 -c 'import json,sys,uuid; x=json.load(open(sys.argv[1])); print(uuid.UUID(x["job_id"]))' "$request")
coin_id=$(python3 -c 'import json,sys,uuid; x=json.load(open(sys.argv[1])); print(uuid.UUID(x["coin_execution_id"]))' "$request")
audit="/var/lib/fc27-cloud/executions/$coin_id.json"
[ -f "$audit" ] && [ ! -L "$audit" ] || exit 2
policy=/var/lib/fc27-cloud/config/player-sync.json
[ -f "$policy" ] && [ ! -L "$policy" ] || exit 2
state=/var/lib/fc27-cloud/state
exec 9>>"$state/price-writer.lock"
flock -w 20 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
ledger=/var/lib/fc27-cloud/player-sync
install -d -o root -g 11028 -m 2770 "$ledger"
set --
parent_id=$(python3 -c 'import json,sys,uuid; x=json.load(open(sys.argv[1])); b=x.get("automatic_basis"); print(str(uuid.UUID(b["parent_id"])) if b else "")' "$request")
if [ -n "$parent_id" ]; then
  parent="/var/lib/fc27-cloud/jobs/$parent_id.json"
  coin_ledger="/var/lib/fc27-cloud/all-coin-sync/$coin_id.json"
  [ -f "$parent" ] && [ ! -L "$parent" ] || exit 2
  [ -f "$coin_ledger" ] && [ ! -L "$coin_ledger" ] || exit 2
  set -- --mount type=bind,src="$parent",dst=/run/automatic-parent.json,readonly \
    --mount type=bind,src="$coin_ledger",dst=/run/coin-all-ledger.json,readonly \
    --mount type=bind,src=/opt/fc27-cloud-browser/coin_all_sync_job.py,dst=/opt/coin_all_sync_job.py,readonly \
    --mount type=bind,src=/opt/fc27-cloud-browser/storefront_monitor.py,dst=/opt/storefront_monitor.py,readonly
fi
probe=$(python3 -c 'import json,sys; print("1" if json.load(open(sys.argv[1])).get("recovery_preflight") is True else "0")' "$request")
limit=3600
if [ "$probe" = 1 ]; then
  coin_ledger="/var/lib/fc27-cloud/all-coin-sync/$coin_id.json"
  [ -f "$coin_ledger" ] && [ ! -L "$coin_ledger" ] || exit 2
  set -- --mount type=bind,src="$coin_ledger",dst=/run/coin-all-ledger.json,readonly \
    --mount type=bind,src=/opt/fc27-cloud-browser/coin_all_sync_job.py,dst=/opt/coin_all_sync_job.py,readonly \
    --mount type=bind,src=/opt/fc27-cloud-browser/storefront_monitor.py,dst=/opt/storefront_monitor.py,readonly
  limit=150
fi
timeout "$limit"s docker run --rm --network fc27-cloud-net --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  --mount type=bind,src=/opt/fc27-cloud-browser/fc_shared_admin.py,dst=/usr/local/bin/p2pah_session_service.py,readonly \
  -e FS_ADMIN_API_BASE=http://172.20.0.1:8913 \
  --mount type=bind,src=/var/lib/fc27-cloud/config,dst=/run/config,readonly \
  --mount type=bind,src="$audit",dst=/run/coin-execution.json,readonly \
  --mount type=bind,src="$request",dst=/run/request.json,readonly \
  --mount type=bind,src="$ledger",dst=/run/player-sync \
  --mount type=bind,src=/opt/fc27-cloud-browser/player_sync_job.py,dst=/opt/player_sync_job.py,readonly \
  "$@" \
  --entrypoint python3 fc27-cloud-session:1 /opt/player_sync_job.py

