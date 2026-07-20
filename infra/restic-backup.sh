#!/bin/sh
set -eu

dump_path=$(./infra/backup.sh)
trap 'rm -f "$dump_path"' EXIT HUP INT TERM
restic backup "$dump_path" --tag mt-rotator-postgres
restic forget \
    --tag mt-rotator-postgres \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 6 \
    --prune
