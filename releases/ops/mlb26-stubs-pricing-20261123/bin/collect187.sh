#!/bin/sh
set -eu

case "${1:-}" in
    PS|XBOX) ;;
    *) exit 2 ;;
esac
[ "$#" -eq 1 ] || exit 2
: "${MLB_BROWSER_IMAGE:?Set the ID of the approved local Chrome image}"
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
exec docker run --rm --init --pull=never --shm-size=1g --memory=3g \
    --mount "type=bind,src=$root,dst=/mlb26,readonly" \
    --workdir /mlb26 --env PYTHONPATH=/mlb26 --entrypoint timeout "$MLB_BROWSER_IMAGE" \
    -k 2s 24s python3 -B -m source.cli primary "$1" --chrome
