#!/usr/bin/env bash
# MLB 新卡上架工作台 —— 服务器端安装脚本（幂等，可反复跑）
#
# 做四件事：
#   1. 装服务本体到 /opt/mlb-online + systemd 自启
#   2. 建静态根 /var/www/mlb-online
#   3. 在 iggm-web.conf 里插 nginx 段（带标记，重复跑不会重复插）
#   4. nginx -t 校验，失败自动回滚
#
# 用法：bash install_mlb.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR=/opt/mlb-online
WEB_DIR=/var/www/mlb-online
NGINX_CONF=/etc/nginx/conf.d/iggm-web.conf
PORT=8897
MARK_BEGIN="# >>> mlb-online (auto) >>>"
MARK_END="# <<< mlb-online (auto) <<<"

if [ ! -f "$SRC_DIR/server/mlb_server.py" ]; then
  echo "[X] 找不到 $SRC_DIR/server/mlb_server.py"
  echo "    这个脚本要放在 <包根>/deploy/ 下跑（包根里应有 server/ 和 web/）"
  exit 1
fi
echo "    源目录：$SRC_DIR"

echo "=== 1/5 安装服务本体 ==="
mkdir -p "$APP_DIR" "$APP_DIR/data" "$APP_DIR/files" "$WEB_DIR"
install -m 644 "$SRC_DIR/server/mlb_server.py" "$APP_DIR/mlb_server.py"
install -m 644 "$SRC_DIR/server/server_config.json" "$APP_DIR/server_config.json"
cp -r "$SRC_DIR/web/." "$WEB_DIR/"
chmod -R a+rX "$WEB_DIR"
chown -R root:root "$APP_DIR"
echo "    $APP_DIR/mlb_server.py"
echo "    $WEB_DIR/index.html"

echo "=== 2/5 安装 systemd 服务 ==="
cat > /etc/systemd/system/mlb-online.service <<'UNIT'
[Unit]
Description=MLB 新卡上架在线工作台（网页 + 任务队列）
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/mlb-online
ExecStart=/usr/bin/python3 /opt/mlb-online/mlb_server.py --port 8897 --root /var/www/mlb-online
Restart=always
RestartSec=3
# 只监听回环，外网一律走 nginx
Environment=PYTHONUNBUFFERED=1
MemoryMax=180M

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable mlb-online.service >/dev/null 2>&1 || true
systemctl restart mlb-online.service
sleep 1
systemctl is-active mlb-online.service

echo "=== 3/5 检查本机接口 ==="
if curl -sf --max-time 10 "http://127.0.0.1:$PORT/api/health" >/dev/null; then
  echo "    本机 /api/health 正常"
else
  echo "    [!] 服务没起来，看日志：journalctl -u mlb-online -n 50 --no-pager"
  exit 1
fi

echo "=== 4/5 配置 nginx ==="
STAMP=$(date +%Y%m%d_%H%M%S)
cp "$NGINX_CONF" "$NGINX_CONF.bak.$STAMP"
echo "    已备份 -> $NGINX_CONF.bak.$STAMP"

# 先删掉旧的自动段（如果之前装过），再插新的
python3 - "$NGINX_CONF" "$MARK_BEGIN" "$MARK_END" <<'PY'
import sys, re
path, mb, me = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path, encoding="utf-8").read()
block = '''
    %s
    # MLB 新卡上架在线工作台：前端页面 + 任务队列（后端 127.0.0.1:8897）
    # 采集由本机执行器完成（服务器出口 IP 过不了 showdd 的 Cloudflare 挑战）
    location = /mlb { return 301 /mlb/; }
    location /mlb/ {
        auth_basic "MLB Tool";
        auth_basic_user_file /etc/nginx/.htpasswd-dashboard;

        proxy_pass http://127.0.0.1:8897/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 关键：把 Basic Auth 用户名注入后端，决定「这次提交算谁的」
        proxy_set_header X-Remote-User $remote_user;

        client_max_body_size 64m;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        expires -1;
    }
    %s
''' % (mb, me)

if mb in src and me in src:
    src = re.sub(re.escape(mb) + r".*?" + re.escape(me), block.strip(), src, flags=re.S)
    print("    已替换旧段落")
else:
    # 插到 server 块内最后一个 } 之前
    idx = src.rstrip().rfind("}")
    src = src[:idx] + block + "\n" + src[idx:]
    print("    已插入新段落")

open(path, "w", encoding="utf-8").write(src)
PY

echo "=== 5/5 校验并生效 nginx ==="
# 注意：判据是 nginx -t 的退出码，不是输出文字。
# 输出里 "syntax is ok" 只覆盖 nginx.conf 本身，包含进来的 server 块报错时
# 照样会出现这行，只看文字会误判（踩过一次）。
if nginx -t > /tmp/nginx_t.log 2>&1; then
  systemctl reload nginx
  echo "    nginx 已 reload"
else
  echo "    [X] nginx -t 不通过，回滚"
  cat /tmp/nginx_t.log
  cp "$NGINX_CONF.bak.$STAMP" "$NGINX_CONF"
  nginx -t && systemctl reload nginx
  echo "    已回滚到备份"
  exit 1
fi

echo
echo "============================================================"
echo "  MLB 工作台部署完成"
echo "  服务   mlb-online.service  127.0.0.1:$PORT"
echo "  页面   http://47.85.224.112/mlb/"
echo "  账号   wulv / （请向管理员单独获取）（与看板同一套）"
echo "  日志   journalctl -u mlb-online -n 50 --no-pager"
echo "============================================================"
