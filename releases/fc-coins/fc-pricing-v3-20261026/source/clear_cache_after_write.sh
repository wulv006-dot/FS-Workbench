#!/bin/sh
set -eu
umask 077
execution_id=${1:?execution_id_required}
case "$execution_id" in
  *[!0-9a-f-]*|'') exit 2 ;;
esac
audit="/var/lib/fc27-cloud/executions/$execution_id.json"
v3_audit="/var/lib/fc27-cloud/v3/cache-authorizations/$execution_id.json"
if [ -f "$v3_audit" ]; then audit="$v3_audit"; fi
[ -f "$audit" ] && [ ! -L "$audit" ] || exit 2
timeout 160s docker run --rm --network fc27-cloud-net --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  --mount type=bind,src=/opt/fs-order-session/fc_shared_admin.py,dst=/usr/local/bin/p2pah_session_service.py,readonly \
  --mount type=bind,src=/etc/fc27-cloud/global-admin-principal.json,dst=/run/secrets/fs-global-admin.json,readonly \
  -e FS_ADMIN_SESSION_URL=http://fc27-p2pah-session:8767 \
  --mount type=bind,src="$audit",dst=/run/coin-execution.json,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/clear_cache_after_write.py,dst=/opt/clear_cache_after_write.py,readonly \
  --entrypoint python3 fc27-cloud-session:1 /opt/clear_cache_after_write.py "$execution_id"
