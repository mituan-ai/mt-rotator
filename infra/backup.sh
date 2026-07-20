#!/bin/sh
set -eu

backup_root=${BACKUP_DIR:-./backups}
case "$backup_root" in
    /|""|.)
        echo "BACKUP_DIR must be a dedicated directory" >&2
        exit 1
        ;;
esac

umask 077
mkdir -p "$backup_root"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
temporary="$backup_root/.mt-rotator-$timestamp.sql.gz.tmp"
destination="$backup_root/mt-rotator-$timestamp.sql.gz"

trap 'rm -f "$temporary"' EXIT HUP INT TERM
docker compose exec -T postgres sh -ec '
    set -o pipefail
    pg_dump \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --format=plain \
        --no-owner \
        --no-privileges | gzip -9
' > "$temporary"
gzip -t "$temporary"
mv "$temporary" "$destination"
trap - EXIT HUP INT TERM

echo "$destination"
