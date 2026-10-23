#!/bin/sh
set -eu

profile=/var/lib/fc27-cloud/browser/lootbar
test -d "$profile"
test -w "$profile"

# Xvfb chooses a free display and signals readiness; stale X99 files stay untouched.
display_file=$(mktemp /tmp/fc27-display.XXXXXX)
trap 'rm -f "$display_file"' 0
Xvfb -displayfd 3 -screen 0 1440x900x24 -nolisten tcp 3>"$display_file" >/dev/null &
xvfb_pid=$!
if display_number=$(python3 - "$display_file" "$xvfb_pid" <<'PY'
import os
import sys
import time


def wait_display(path, pid, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with open(path, "rb") as handle:
            data = handle.read(32)
        if data.endswith(b"\n"):
            value = data[:-1]
            if not value or not value.isdigit() or len(value) > 5:
                raise RuntimeError("xvfb_invalid_display_number")
            os.kill(pid, 0)
            return str(int(value))
        if len(data) >= 32:
            raise RuntimeError("xvfb_invalid_display_number")
        try:
            with open("/proc/%s/stat" % pid) as handle:
                if handle.read().rsplit(")", 1)[1].split()[0] == "Z":
                    raise RuntimeError("xvfb_exited_before_ready")
            os.kill(pid, 0)
        except ProcessLookupError:
            raise RuntimeError("xvfb_exited_before_ready") from None
        except FileNotFoundError:
            raise RuntimeError("xvfb_exited_before_ready") from None
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    raise RuntimeError("xvfb_readiness_timeout")


if __name__ == "__main__":
    try:
        print(wait_display(sys.argv[1], int(sys.argv[2])))
    except (OSError, RuntimeError) as error:
        print("FC browser display startup failed: %s" % error, file=sys.stderr)
        sys.exit(1)
PY
); then
    DISPLAY=":$display_number"
    export DISPLAY
else
    kill "$xvfb_pid" 2>/dev/null || :
    exit 1
fi
rm -f "$display_file"
trap - 0
x11vnc -display "$DISPLAY" -rfbport 5905 -localhost -forever -shared -nopw -quiet >/dev/null 2>&1 &
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
