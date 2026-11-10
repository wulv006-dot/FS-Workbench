#!/bin/sh
set -eu
/opt/hermes/.venv/bin/python -B /profile/scripts/fs-ops-watchdog/watch.py check
/opt/hermes/.venv/bin/python -B /profile/scripts/fs-ops-watchdog/watch.py review
