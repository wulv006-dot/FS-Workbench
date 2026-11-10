#!/bin/sh
set -eu
/opt/hermes/.venv/bin/python -B /profile/scripts/fs-ops-watchdog/pricing_watch.py
/opt/hermes/.venv/bin/python -B /profile/scripts/fs-ops-watchdog/watch.py review
