#!/bin/sh
set -eu

cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export N8N_USER_FOLDER="$PWD/n8n-data"
export N8N_LISTEN_ADDRESS=127.0.0.1
export N8N_HOST=localhost
export N8N_PORT=5679
export N8N_DEFAULT_BINARY_DATA_MODE=filesystem
export N8N_RESTRICT_FILE_ACCESS_TO="$PWD/runs"
export N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
export N8N_DIAGNOSTICS_ENABLED=false
export N8N_VERSION_NOTIFICATIONS_ENABLED=false

case "${1:-start}" in
    init) n8n import:workflow --separate --input=workflows ;;
    start) exec n8n start ;;
    *) echo "Kullanım: sh n8n-local.sh [init|start]" >&2; exit 2 ;;
esac
