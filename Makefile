.PHONY: help start stop restart logs clean status migrate test lint format build

# Default target
help:
	@echo "VOICEcheck - Available commands:"
	@echo ""
	@echo "Development:"
	@echo "  start          - Start all services"
	@echo "  stop           - Stop all services"
	@echo "  restart        - Restart all services"
	@echo "  status         - Show service status"
	@echo "  logs           - Show logs"
	@echo "  clean          - Clean all containers and volumes"
	@echo ""
	@echo "Database:"
	@echo "  migrate        - Run database migrations"
	@echo "  migrate-down   - Rollback last migration"
	@echo ""
	@echo "Code Quality:"
	@echo "  test           - Run tests"
	@echo "  lint           - Run linter"
	@echo "  format         - Format code"
	@echo ""
	@echo "Build:"
	@echo "  build          - Build Docker images"
	@echo "  build-no-cache - Build Docker images without cache"

# Environment variables
COMPOSE_FILE=docker-compose.yml
ENV_FILE=.env

# Development commands
start:
	@echo "Starting VOICEcheck..."
	docker compose up -d
	@echo "Services started. Use 'make logs' to view logs."

stop:
	@echo "Stopping VOICEcheck..."
	docker compose down

restart:
	@echo "Restarting VOICEcheck..."
	docker compose restart

status:
	@echo "SERVICE STATUS:"
	docker compose ps

logs:
	@echo "Showing logs for voicecheck service..."
	docker compose logs -f voicecheck

logs-all:
	@echo "Showing logs for all services..."
	docker compose logs -f

clean:
	@echo "Cleaning VOICEcheck..."
	docker compose down -v
	@echo "Clean completed!"

# Database commands
migrate:
	@echo "Running database migrations..."
	docker compose exec voicecheck alembic upgrade head

migrate-down:
	@echo "Rolling back last migration..."
	docker compose exec voicecheck alembic downgrade -1

migrate-history:
	@echo "Migration history:"
	docker compose exec voicecheck alembic history

# Code quality commands
test:
	@echo "Running tests..."
	docker compose exec voicecheck python -m pytest -v

test-unit:
	@echo "Running unit tests..."
	docker compose exec voicecheck python -m pytest tests/ -m "not integration"

test-integration:
	@echo "Running integration tests..."
	docker compose exec voicecheck python -m pytest tests/ -m "integration"

lint:
	@echo "Running linter..."
	docker compose exec voicecheck python -m flake8 app/

format:
	@echo "Formatting code..."
	docker compose exec voicecheck python -m black app/ alembic/

# Build commands
build:
	@echo "Building Docker images..."
	docker compose build

build-no-cache:
	@echo "Building Docker images without cache..."
	docker compose build --no-cache

# Development helpers
shell:
	@echo "Opening shell in voicecheck container..."
	docker compose exec voicecheck bash

shell-db:
	@echo "Opening shell in database container..."
	docker compose exec postgres bash

shell-migration:
	@echo "Opening shell in migration container..."
	docker compose --profile migrations exec migration bash

# Health check
health:
	@echo "Checking service health..."
	./scripts/health-check.sh

# Quick setup
setup:
	@echo "Setting up VOICEcheck..."
	@echo "1. Creating .env file..."
	@cp .env.example .env
	@echo "2. Please edit .env file with your API keys!"
	@echo "3. Starting services..."
	@make start
	@echo "4. Running migrations..."
	@make migrate
	@echo "Setup complete!"

# Production commands
prod-start:
	@echo "Starting in production mode..."
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

prod-stop:
	@echo "Stopping production services..."
	docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# Debug commands
debug-logs:
	@echo "Debug logs with timestamps..."
	docker compose logs --timestamps -f voicecheck

debug-health:
	@echo "Debug health checks..."
	@echo "PostgreSQL:"
	docker compose exec postgres pg_isready -U ${POSTGRES_USER:-voicecheck} -d ${POSTGRES_DB:-voicecheck}
	@echo "Application:"
	curl -v http://localhost:8000/health