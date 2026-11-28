#!/bin/sh
set -eu

: "${MLB_PRIMARY_WORKER:?Set the path to the authorized 187 collector}"
set -- "${MLB_PYTHON:-python3}" -B -m source.cli preview \
    --state-dir "${MLB_PREVIEW_DIR:-/var/lib/fs-mlb26-stubs-preview}" \
    --primary-worker "$MLB_PRIMARY_WORKER"
if [ -n "${MLB_BACKUP_WORKER:-}" ]; then
    set -- "$@" --backup-worker "$MLB_BACKUP_WORKER"
fi
if [ -n "${MLB_IGGM_RECEIPT:-}" ]; then
    set -- "$@" --iggm-receipt "$MLB_IGGM_RECEIPT"
fi
if [ -n "${MLB_ORDER_SNAPSHOT:-}" ]; then
    set -- "$@" --order-snapshot "$MLB_ORDER_SNAPSHOT"
fi
exec "$@"
