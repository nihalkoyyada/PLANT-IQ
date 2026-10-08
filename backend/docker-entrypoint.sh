#!/bin/sh
set -e

echo "Checking database migration status..."
alembic upgrade head

echo "Starting application process: $@"
exec "$@"
