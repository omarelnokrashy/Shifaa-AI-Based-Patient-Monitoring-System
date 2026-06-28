#!/usr/bin/env bash
echo "[NOTICE] Launcher has moved to scripts/start_all_services.sh"
exec "$(dirname "$0")/scripts/start_all_services.sh" "$@"
