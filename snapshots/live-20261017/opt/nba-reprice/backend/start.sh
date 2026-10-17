#!/usr/bin/env bash
# 手动 / pm2 启动脚本：读取同目录 .env 后启动 server.js
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec node server.js
