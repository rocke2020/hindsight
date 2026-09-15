#!/bin/bash
set -euo pipefail

# Rebuilds the control plane standalone production build from the hindsight
# checkout, then restarts the launchd service. The hindsight checkout is treated
# as read-only upstream source: `next build` dirties tsconfig.json by appending
# .next-* type includes, so that file is restored to git HEAD afterwards when
# it was clean before the build.

readonly HINDSIGHT_CHECKOUT="/Users/rocke_dong/codes/hindsight"
readonly RESTART_SCRIPT="/Users/rocke_dong/codes/hindsight2/learning/start_service/restart_control_plane.sh"
readonly TSCONFIG="${HINDSIGHT_CHECKOUT}/hindsight-control-plane/tsconfig.json"

for required_file in "${HINDSIGHT_CHECKOUT}/.env" "${HINDSIGHT_CHECKOUT}/hindsight-control-plane/package.json" "${RESTART_SCRIPT}"; do
    if [[ ! -f "${required_file}" ]]; then
        echo "Required file is missing: ${required_file}" >&2
        exit 78
    fi
done

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

if git -C "${HINDSIGHT_CHECKOUT}" diff --quiet -- "${TSCONFIG#${HINDSIGHT_CHECKOUT}/}"; then
    TS_HAD_LOCAL_CHANGES=0
else
    TS_HAD_LOCAL_CHANGES=1
fi

cd "${HINDSIGHT_CHECKOUT}"

if [ "$RUN_UPDATE" = true ]; then
    echo "Building TypeScript SDK..."
    /usr/bin/env npm run build -w @vectorize-io/hindsight-client

    echo "Building control plane standalone..."
    /usr/bin/env npm run build -w hindsight-control-plane
else
    echo "Skipping rebuild (--no-update)"
fi

if [ "${TS_HAD_LOCAL_CHANGES}" -eq 0 ] && ! git diff --quiet -- "${TSCONFIG#${HINDSIGHT_CHECKOUT}/}"; then
    echo "Restoring tsconfig.json dirtied by next build (checkout was clean before)..."
    git checkout -- hindsight-control-plane/tsconfig.json
fi

bash "${RESTART_SCRIPT}"
