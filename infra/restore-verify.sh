#!/bin/sh
set -eu

[ "$#" -eq 0 ] || {
    echo "restore verification now uses the latest restic snapshot" >&2
    exit 2
}
exec "$(dirname "$0")/../ops/mt-rotator" restore-verify
