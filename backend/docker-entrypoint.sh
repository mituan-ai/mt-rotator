#!/bin/sh
set -eu

if [ "${RUN_STARTUP_TASKS:-false}" = "true" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    python manage.py seed_catalog
fi

exec "$@"
