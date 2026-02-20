#!/bin/bash
# Health check script for VOICEcheck

set -e

APP_URL=${APP_URL:-http://localhost:8000}

echo "Checking VOICEcheck health..."

# Check application health
if curl -f "${APP_URL}/health" &>/dev/null; then
    echo "✓ Application is healthy"
    curl -s "${APP_URL}/health" | python3 -m json.tool
else
    echo "✗ Application is not responding"
    exit 1
fi

# Check database connection
if docker compose exec -T postgres pg_isready -U ${POSTGRES_USER:-voicecheck} -d ${POSTGRES_DB:-voicecheck}; then
    echo "✓ Database is healthy"
else
    echo "✗ Database is not responding"
    exit 1
fi

echo "All services are healthy!"