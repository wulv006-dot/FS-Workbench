#!/bin/sh
# Admin uses the DC proxy; the existing idempotent host fallback remains.
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

rc=0
timeout 160s docker run --rm --network fc27-cloud-net --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  --mount type=bind,src=/opt/fc27-cloud-browser/fc_shared_admin.py,dst=/usr/local/bin/p2pah_session_service.py,readonly \
  -e FS_ADMIN_API_BASE=http://172.20.0.1:8913 \
  --mount type=bind,src="$audit",dst=/run/coin-execution.json,readonly \
  --mount type=bind,src=/opt/fc27-cloud-browser/clear_cache_after_write.py,dst=/opt/clear_cache_after_write.py,readonly \
  --entrypoint python3 fc27-cloud-session:1 /opt/clear_cache_after_write.py "$execution_id" || rc=$?

if [ "$rc" -eq 0 ]; then
  exit 0
fi

echo "[clear_cache] 容器路径失败 rc=$rc → 改走宿主机 dc-proxy 补清（执行 $execution_id）" >&2
body=$(curl -s --max-time 40 -w '\n%{http_code}' -X POST "http://127.0.0.1:8912/admin/tools.Caches/clear?server=1" \
        -H 'Content-Type: application/json' -d '{"type":"all","file":""}') || body=""
echo "[clear_cache] dc-proxy 回执已收取" >&2
if printf '%s' "$body" | /opt/python39/bin/python3 -B /opt/fc27-cloud-browser/clear_cache_after_write.py --host-receipt "$execution_id"; then
  exit 0
fi
exit "$rc"
