#!/usr/bin/env bash
# IGGM Price Scraper - Web edition (no login, global shared queue)
# One-shot deployment for CentOS / RHEL / Rocky / AlmaLinux 8 / 9 (RHEL family).
# Run as root:   bash deploy/setup.sh
#
# 适配说明（与 Ubuntu 版差异）：
#   - 包管理器: dnf (CentOS 8+/RHEL 8+/Rocky 8+/AlmaLinux 8+) 或 yum (CentOS 7)
#   - nginx 不在基础源，先装 epel-release
#   - CentOS 8 / Rocky 8 / RHEL 8 / AlmaLinux 8 默认 python3 = 3.6（Flask3 需 3.8+），
#     用 `dnf module enable python39` 切到 3.9；CentOS 7（EOL）默认 python3 仅 3.6，
#     Flask>=3.0 跑不动，建议升级到 9.x
#   - SELinux 默认开启：放行 nginx 反代后端需要 setsebool httpd_can_network_connect=1
#   - 防火墙是 firewalld，需要 firewall-cmd --add-port=80/tcp（云上还需安全组放行）
set -euo pipefail

APP_DIR=/opt/iggm-web
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$APP_DIR/venv"
SERVICE=iggm-web
PORT=8787

# ---- 包管理器选择 ----
if command -v dnf >/dev/null 2>&1; then
  PM=dnf
elif command -v yum >/dev/null 2>&1; then
  PM=yum
else
  echo "!! 找不到 dnf / yum，本脚本仅支持 RHEL 系列发行版"
  exit 1
fi

# ---- CentOS 大版本探测（影响是否需要 dnf module 切 python39）----
MAJOR_VER=""
if [ -r /etc/os-release ]; then
  . /etc/os-release
  case "$ID${VERSION_ID}" in
    rhel*8*|rocky*8*|almalinux*8*|centos*8*) MAJOR_VER=8 ;;
    rhel*9*|rocky*9*|almalinux*9*|centos*9*) MAJOR_VER=9 ;;
    *) MAJOR_VER="${VERSION_ID%%.*}" ;;
  esac
fi

echo "==> [1/7] install system packages (pm=$PM, major=$MAJOR_VER)"

# EPEL: nginx 在 CentOS 8 基础源里没有，9.x 也常用，先装上
if ! rpm -q epel-release >/dev/null 2>&1; then
  $PM install -y -q epel-release || true
fi

# 8.x 默认 python3 = 3.6，Flask3 要 3.8+，用 dnf module 切到 python39
if [ "$MAJOR_VER" = "8" ]; then
  $PM module reset -y python3 >/dev/null 2>&1 || true
  $PM module enable -y python39 >/dev/null 2>&1 || true
fi

# 7.x 默认 python3 = 3.6，Flask3 / Werkzeug 已经跑不动；给一个明确提示而不是默默失败
if [ "$MAJOR_VER" = "7" ]; then
  echo "!! 检测到 CentOS/RHEL 7（已 EOL）。默认 python3 仅 3.6，无法满足 Flask>=3.0 要求。"
  echo "   建议：升级到 Rocky/AlmaLinux 9，或自行安装 Python 3.9+ 后改 \$PY 变量重跑。"
  exit 1
fi

$PM install -y -q python3 python3-venv python3-pip nginx || {
  echo "!! 包安装失败。若是离线环境，请先在能上网的同版本机器上 yumdownloader 准备好 rpm"
  exit 1
}

# 确认 python3 版本可用
PY_BIN=python3
PY_VER=$("$PY_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
case "$PY_VER" in
  3.8|3.9|3.10|3.11|3.12|3.13|3.14) ;;
  *) echo "!! 系统 python3 = $PY_VER，Flask>=3.0 需要 3.8+，请升级后重跑"; exit 1 ;;
esac
echo "    python3 = $PY_VER"

echo "==> [2/7] sync code to $APP_DIR"
mkdir -p "$APP_DIR"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  (cd "$SRC_DIR" && tar --exclude=venv --exclude=data --exclude=__pycache__ -cf - .) \
    | (cd "$APP_DIR" && tar -xf -)
fi
mkdir -p "$APP_DIR/data/exports"

echo "==> [3/7] create virtualenv"
if [ ! -x "$VENV/bin/python" ]; then
  "$PY_BIN" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt" -q

echo "==> [4/7] write .env"
if [ ! -f "$APP_DIR/.env" ]; then
  SECRET="$("$VENV/bin/python" -c 'import secrets;print(secrets.token_hex(32))')"
  cat > "$APP_DIR/.env" <<EOF
IGGM_SECRET=$SECRET
IGGM_DATA=$APP_DIR/data
IGGM_EXPORTS=$APP_DIR/data/exports
IGGM_PORT=$PORT
# 可选：设置后打开网页要输一次口令（记住 30 天），不设置则完全开放
# IGGM_ACCESS_CODE=your-team-code
EOF
  chmod 600 "$APP_DIR/.env"
fi

echo "==> [5/7] create systemd service"
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=IGGM Price Scraper Web
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
# -w 1 is REQUIRED: the task queue lives in process memory,
# multiple workers would split the queue and hide running tasks.
ExecStart=$VENV/bin/gunicorn -w 1 -k gthread --threads 8 \\
  --timeout 600 --graceful-timeout 30 \\
  --bind 127.0.0.1:$PORT app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "==> [6/7] configure nginx + SELinux + firewalld"
cat > /etc/nginx/conf.d/iggm-web.conf <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 2m;

    location / {
        proxy_pass       http://127.0.0.1:8787;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
EOF
# 防止 nginx.conf 主 server 块占 default_server 冲突
if grep -qE '^\s*listen\s+80\s+default_server' /etc/nginx/nginx.conf 2>/dev/null; then
  sed -i 's/^\(\s*\)listen \(80\s\+default_server\)/\1listen \2 # moved to conf.d\/iggm-web.conf/' /etc/nginx/nginx.conf
fi

# SELinux：默认开启会让 nginx 反代到 127.0.0.1 被拒（permission denied），放行一下
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" != "Disabled" ]; then
  setsebool -P httpd_can_network_connect 1
  echo "    SELinux: httpd_can_network_connect=1"
fi

# firewalld：CentOS 默认防火墙，放行 80
if systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --permanent --add-port=80/tcp >/dev/null
  firewall-cmd --reload >/dev/null
  echo "    firewalld: TCP/80 opened"
fi

systemctl daemon-reload
systemctl enable --now "$SERVICE"
nginx -t && systemctl enable --now nginx

echo "==> [7/7] done"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-127.0.0.1}"
cat <<EOF

============================================================
 Deployment done.  Open in browser:  http://$IP/

 No login required - everyone shares one global queue.
 If unreachable: open TCP/80 in cloud security group AND
                 check 'firewall-cmd --list-port'.

 Optional: set IGGM_ACCESS_CODE in $APP_DIR/.env
           to require a one-time team passcode, then:
           systemctl restart $SERVICE

 Useful commands:
   systemctl status  $SERVICE
   systemctl restart $SERVICE
   journalctl -u $SERVICE -f
============================================================
EOF