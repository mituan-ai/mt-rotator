#!/bin/sh
set -eu

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Usage: $0 path/to/mt-rotator-YYYYMMDDTHHMMSSZ.sql.gz" >&2
    exit 1
fi

archive=$1
case "$archive" in
    *.sql.gz) ;;
    *)
        echo "Backup must end with .sql.gz" >&2
        exit 1
        ;;
esac

verify_db="mt_rotator_verify_$(date -u +%Y%m%d%H%M%S)_$$"
cleanup() {
    docker compose exec -T postgres sh -ec '
        dropdb --if-exists --force --username "$POSTGRES_USER" "$1"
    ' sh "$verify_db" >/dev/null
}
trap cleanup EXIT HUP INT TERM

gzip -t "$archive"
docker compose exec -T postgres sh -ec '
    createdb --username "$POSTGRES_USER" "$1"
' sh "$verify_db"
gzip -dc "$archive" | docker compose exec -T postgres sh -ec '
    psql --username "$POSTGRES_USER" --dbname "$1" --set ON_ERROR_STOP=1
' sh "$verify_db" >/dev/null
docker compose exec -T postgres sh -ec '
    psql \
        --username "$POSTGRES_USER" \
        --dbname "$1" \
        --tuples-only \
        --command "SELECT COUNT(*) FROM django_migrations; SELECT COUNT(*) FROM accounts_user;"
' sh "$verify_db"

echo "Restore verification succeeded: $archive"
