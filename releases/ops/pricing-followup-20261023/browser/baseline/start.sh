#!/bin/sh
set -eu

profile=/var/lib/fc27-cloud/browser/lootbar
test -d "$profile"
test -w "$profile"

Xvfb :99 -screen 0 1440x900x24 -nolisten tcp >/dev/null 2>&1 &
sleep 2
x11vnc -display :99 -rfbport 5905 -localhost -forever -shared -nopw -quiet >/dev/null 2>&1 &
websockify --web /usr/share/novnc 0.0.0.0:6082 127.0.0.1:5905 >/dev/null 2>&1 &
socat TCP-LISTEN:9226,bind=0.0.0.0,reuseaddr,fork TCP:127.0.0.1:9225 >/dev/null 2>&1 &

exec google-chrome-stable \
  --no-sandbox \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --user-data-dir="$profile" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9225 \
  https://www.lootbar.com/game-coins/fc27
