#!/bin/bash
set -euo pipefail

# Restarts both local Hindsight services via launchd:
#   - API (port 8888)          -> restart_hindsight_service.sh
#   - Control Plane UI (9999)  -> restart_control_plane.sh
# Order matters: the API must be healthy before the control plane starts,
# otherwise the UI boots against a dead dataplane URL.

readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

bash "${SCRIPT_DIR}/restart_hindsight_service.sh"
bash "${SCRIPT_DIR}/restart_control_plane.sh"

echo ""
echo "Hindsight is running:"
echo "  API:           http://localhost:8888"
echo "  Control Plane: http://localhost:9999"
