#!/usr/bin/env bash
# MMOEXP price scraper Web deployment for Ubuntu 22.04/24.04
# Run as root from /opt/iggm-web:
#   bash deploy/setup_ubuntu.sh
set -euo pipefail

APP_DIR="/opt/iggm-web"
VENV="$APP_DIR/venv"
SERVICE="iggm-web"
PORT="8787"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root."
  exit 1
fi

if [ ! -f "$APP_DIR/app.py" ]; then
  echo "Missing $APP_DIR/app.py"
  exit 1
fi

echo "==> [1/7] install system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx curl ca-certificates

PY_BIN="$(command -v python3)"
PY_VER="$($PY_BIN -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "    python3 = $PY_VER"

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> [2/7] create virtualenv"
  "$PY_BIN" -m venv "$VENV"
else
  echo "==> [2/7] reuse virtualenv"
fi

"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/data/exports"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "==> [3/7] create environment file"
  SECRET="$($VENV/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
  cat > "$APP_DIR/.env" <<EOF
IGGM_SECRET=$SECRET
IGGM_DATA=$APP_DIR/data
IGGM_EXPORTS=$APP_DIR/data/exports
IGGM_PORT=$PORT
# Public no-login mode. Add IGGM_ACCESS_CODE here only if a team passcode is wanted.
EOF
  chmod 600 "$APP_DIR/.env"
else
  echo "==> [3/7] reuse existing environment file"
fi

chown -R root:root "$APP_DIR"
chmod 700 "$APP_DIR/data" "$APP_DIR/data/exports"

# A stale database task cannot block a fresh service after a reboot.
echo "==> [4/7] create systemd service"
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=MMOEXP Game Price Scraper Web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV/bin/gunicorn -w 1 -k gthread --threads 8 --timeout 600 --graceful-timeout 30 --bind 127.0.0.1:$PORT app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Remove Ubuntu's default virtual host, but keep other site configs intact.
echo "==> [5/7] configure nginx"
rm -f /etc/nginx/sites-enabled/default
cat > /etc/nginx/conf.d/iggm-web.conf <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
EOF

nginx -t

echo "==> [6/7] enable services and firewall"
systemctl daemon-reload
systemctl enable --now "$SERVICE"
systemctl enable --now nginx
if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp || true
fi

sleep 2
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "Service failed to start. Recent log:"
  journalctl -u "$SERVICE" -n 50 --no-pager
  exit 1
fi
if ! systemctl is-active --quiet nginx; then
  echo "Nginx failed to start. Recent log:"
  journalctl -u nginx -n 50 --no-pager
  exit 1
fi

echo "==> [7/7] deployment complete"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-127.0.0.1}"
echo "Open: http://$IP/"
echo "Mode: public, no login, shared queue"
echo "Health: curl http://127.0.0.1/healthz"
