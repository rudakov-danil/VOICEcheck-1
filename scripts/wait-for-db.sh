#!/bin/bash
# Wait for database to be ready script

set -e

# Database configuration
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5432}
DB_USER=${POSTGRES_USER:-voicecheck}
DB_NAME=${POSTGRES_DB:-voicecheck}

echo "Waiting for PostgreSQL database at ${DB_HOST}:${DB_PORT}..."

# Maximum wait time in seconds
MAX_WAIT=30
WAIT_COUNT=0

while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if docker compose exec -T postgres pg_isready -U ${DB_USER} -d ${DB_NAME}; then
        echo "PostgreSQL is ready!"
        exit 0
    fi
    echo "Waiting for PostgreSQL... (${WAIT_COUNT}s)"
    sleep 1
    WAIT_COUNT=$((WAIT_COUNT + 1))
done

echo "Error: PostgreSQL did not become ready within ${MAX_WAIT} seconds"
exit 1