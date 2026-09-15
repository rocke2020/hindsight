#!/bin/bash
set -euo pipefail

readonly HINDSIGHT_CHECKOUT="/Users/rocke_dong/codes/hindsight"
readonly RESTART_SCRIPT="/Users/rocke_dong/codes/hindsight2/learning/start_service/restart_hindsight_service.sh"

RUN_UPDATE=true
for arg in "$@"; do
    if [ "$arg" = "--no-update" ]; then
        RUN_UPDATE=false
    else
        echo "Unknown option: ${arg}" >&2
        echo "Usage: $0 [--no-update]" >&2
        exit 64
    fi
done

for required_file in "${HINDSIGHT_CHECKOUT}/.env" "${RESTART_SCRIPT}"; do
    if [[ ! -f "${required_file}" ]]; then
        echo "Required file is missing: ${required_file}" >&2
        exit 78
    fi
done

if [ "$RUN_UPDATE" = true ]; then
    for required_file in "${HINDSIGHT_CHECKOUT}/uv.lock"; do
        if [[ ! -f "${required_file}" ]]; then
            echo "Required file is missing: ${required_file}" >&2
            exit 78
        fi
    done

    echo "Syncing uv environment in ${HINDSIGHT_CHECKOUT}..."
    cd "${HINDSIGHT_CHECKOUT}"
    /usr/bin/env uv sync
else
    echo "Skipping uv sync (--no-update)"
    cd "${HINDSIGHT_CHECKOUT}"
fi

echo "Restarting Hindsight service..."
bash "${RESTART_SCRIPT}"
