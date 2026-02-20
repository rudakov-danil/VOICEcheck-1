#!/bin/bash
# Logs viewer for VOICEcheck

set -e

APP_SERVICE=${1:-voicecheck}

show_usage() {
    echo "Usage: $0 [service]"
    echo "Services: voicecheck, postgres, all"
    echo "Examples:"
    echo "  $0 voicecheck    - Show voicecheck logs"
    echo "  $0 postgres     - Show postgres logs"
    echo "  $0 all          - Show all logs"
}

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_usage
    exit 0
fi

if [[ "$1" == "all" ]]; then
    echo "=== ALL LOGS ==="
    docker compose logs -f
else
    echo "=== ${APP_SERVICE} LOGS ==="
    docker compose logs -f ${APP_SERVICE}
fi