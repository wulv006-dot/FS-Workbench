#!/bin/sh
set -eu
stage="$1"
target=/opt/mmoexp-fc-community
test ! -e "$target"
test ! -e /etc/mmoexp-fc-community.env
test ! -e /etc/systemd/system/mmoexp-fc-community.service
if getent passwd mmoexp-fc-community >/dev/null; then
    echo 'Service user already exists; inspect before continuing.' >&2
    exit 1
fi
/opt/python39/bin/python3.9 -c 'import ssl; print(ssl.OPENSSL_VERSION)'
/opt/python39/bin/python3.9 -m venv "$stage/venv"
"$stage/venv/bin/python" -m pip --disable-pip-version-check install -r "$stage/requirements.txt"
cd "$stage"
"$stage/venv/bin/python" -m unittest discover -s tests -v
"$stage/venv/bin/python" content_bot.py --config content.config.json --check
"$stage/venv/bin/python" -m pip check
useradd --system --user-group --no-create-home --shell /sbin/nologin mmoexp-fc-community
install -d -m 0755 "$target"
install -d -o mmoexp-fc-community -g mmoexp-fc-community -m 0700 "$target/var"
install -m 0644 content_bot.py community.py requirements.txt content.config.json "$target/"
/opt/python39/bin/python3.9 -m venv "$target/.venv-ssl"
"$target/.venv-ssl/bin/python" -m pip --disable-pip-version-check install -r "$target/requirements.txt"
install -m 0600 discord.env /etc/mmoexp-fc-community.env
install -m 0644 mmoexp-fc-community.service /etc/systemd/system/mmoexp-fc-community.service
systemd-analyze verify /etc/systemd/system/mmoexp-fc-community.service
systemctl daemon-reload
systemctl enable --now mmoexp-fc-community.service
systemctl is-active mmoexp-fc-community.service
