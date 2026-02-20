#!/bin/bash
# VOICEcheck Startup Script
# Initializes database and starts the application

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .env file exists
if [ ! -f .env ]; then
    print_warning ".env file not found. Creating from .env.example..."
    cp .env.example .env
    print_error "Please edit .env file with your API keys and passwords before starting!"
    exit 1
fi

# Check required environment variables
source .env

print_status "Starting VOICEcheck..."

# Wait for PostgreSQL to be ready
print_status "Waiting for PostgreSQL to be ready..."
until docker compose exec -T postgres pg_isready -U ${POSTGRES_USER:-voicecheck} -d ${POSTGRES_DB:-voicecheck}; do
    print_status "Waiting for PostgreSQL..."
    sleep 2
done

print_status "PostgreSQL is ready!"

# Run migrations
print_status "Running database migrations..."
docker compose exec -T voicecheck alembic upgrade head

# Check if migrations succeeded
if [ $? -eq 0 ]; then
    print_status "Database migrations completed successfully!"
else
    print_error "Database migrations failed!"
    exit 1
fi

# Start the application in foreground
print_status "Starting VOICEcheck application..."
docker compose up -d voicecheck

# Wait for application to start
print_status "Waiting for application to be ready..."
until curl -f http://localhost:8000/health &>/dev/null; do
    print_status "Waiting for application..."
    sleep 2
done

print_status "VOICEcheck is running successfully!"
print_status "Application available at: http://localhost:8000"
print_status "API documentation: http://localhost:8000/docs"

# Show status
docker compose ps