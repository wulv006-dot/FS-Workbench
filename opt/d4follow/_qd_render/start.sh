#!/bin/sh
# 千岛抓取「渲染后端」容器 —— 一键（重）启动
#
# 改动 core_qd.py / qd_render_svc.py 之后不必重建镜像，跑一次本脚本即可生效：
#   core_qd.py 是只读挂载进去的（每次请求现读 config.json、import 同一份代码）
#   qd_render_svc.py 同理，但要重启进程才会重新加载 —— 这就是本脚本的作用。
#
# 重建镜像（换 playwright 版本时才需要）：
#   cd /opt/d4follow/_qd_render && docker build -t qd-render:1.47 .
#
# --init（2026-10-08 加）：用容器内 tini 充当 PID 1，自动 reap 被 Chromium 甩下来
#   的僵尸子进程。加之前容器里累计了数百个 [chrome] <defunct>（Sep27–Oct07 观测），
#   不影响功能但进程表一直涨；加 --init 即可根治，不必重建镜像。
set -e

docker rm -f qd-render >/dev/null 2>&1 || true

docker run -d --name qd-render \
  --init \
  --restart=always \
  -p 127.0.0.1:9223:9223 \
  -v /opt/d4follow:/app:ro \
  -w /app \
  --shm-size=1g \
  --memory=3g \
  --user root \
  -e QD_TZ_OFFSET=8 \
  -e QD_RENDER_URL=off \
  -e PYTHONUNBUFFERED=1 \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e QD_APP_DIR=/app \
  -e QD_CFG=/app/config.json \
  -e QD_PORT=9223 \
  qd-render:1.47 \
  python /app/_qd_render/qd_render_svc.py

sleep 5
docker ps --filter name=qd-render --format '{{.Names}} | {{.Image}} | {{.Status}}'
printf 'health: '
curl -s --max-time 10 http://127.0.0.1:9223/health || echo '(探活失败)'
echo
