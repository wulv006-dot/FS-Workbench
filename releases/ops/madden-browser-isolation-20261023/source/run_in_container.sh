#!/bin/sh
# Original CLI/operation IDs pass through the bounded isolated job runtime.
set -eu
exec /opt/python39/bin/python3 -B /opt/madden-workbench/browser_runtime.py "$@"
