#!/bin/bash
# Clean script for VOICEcheck

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_status "Cleaning VOICEcheck..."

# Stop containers
print_status "Stopping containers..."
docker compose down

# Remove volumes
print_status "Removing volumes..."
docker compose down -v

# Clean up images
print_status "Cleaning up images..."
docker compose down -rmi all

# Clean up build cache
print_status "Cleaning up build cache..."
docker builder prune -f

print_status "Clean completed successfully!"

# Ask if user wants to remove .env file
read -p "Do you want to remove .env file? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f .env
    print_warning ".env file removed"
fi

# Ask if user wants to remove uploads
read -p "Do you want to remove uploads directory? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf uploads
    rm -rf /tmp/voicecheck_uploads
    print_warning "Uploads directory removed"
fi