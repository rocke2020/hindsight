#!/bin/bash
set -euo pipefail

readonly SERVICE_LABEL="com.rocke.hindsight.server"
readonly SERVICE_PLIST="/Users/rocke_dong/Library/LaunchAgents/${SERVICE_LABEL}.plist"
readonly SERVICE_LAUNCHER="/Users/rocke_dong/.hindsight/bin/start-hindsight.sh"
readonly SERVICE_ENV="/Users/rocke_dong/codes/hindsight/.env"
readonly SERVICE_LOG="/Users/rocke_dong/.hindsight/logs/server.log"
readonly HEALTH_URL="http://127.0.0.1:8888/health"
readonly EXPECTED_CONFIG_LOG="Hindsight config source: ${SERVICE_ENV}"
readonly STARTUP_TIMEOUT_SECONDS=90

for required_file in "${SERVICE_PLIST}" "${SERVICE_LAUNCHER}" "${SERVICE_ENV}"; do
    if [[ ! -f "${required_file}" ]]; then
        echo "Required service file is missing: ${required_file}" >&2
        exit 78
    fi
done

if /usr/bin/grep -Fq "/Users/rocke_dong/codes/agent-memory-eval/agent-memory-benchmark/.env" "${SERVICE_LAUNCHER}"; then
    echo "Refusing restart: launcher still references the benchmark .env" >&2
    exit 78
fi

if ! /usr/bin/grep -Fq 'readonly HINDSIGHT_ENV="${HINDSIGHT_CHECKOUT}/.env"' "${SERVICE_LAUNCHER}"; then
    echo "Refusing restart: launcher does not select ${SERVICE_ENV}" >&2
    exit 78
fi

uid_number=$(/usr/bin/id -u)
service_target="gui/${uid_number}/${SERVICE_LABEL}"
old_pid=""
log_start_line=1

if [[ -f "${SERVICE_LOG}" ]]; then
    log_start_line=$(( $(/usr/bin/wc -l < "${SERVICE_LOG}") + 1 ))
fi

if /bin/launchctl print "${service_target}" >/dev/null 2>&1; then
    old_pid=$(/bin/launchctl print "${service_target}" | /usr/bin/awk '/^[[:space:]]*pid = / {print $3; exit}')
    /bin/launchctl kickstart -k "${service_target}"
else
    /bin/launchctl bootstrap "gui/${uid_number}" "${SERVICE_PLIST}"
fi

new_pid=""
health_body=""
for ((attempt = 1; attempt <= STARTUP_TIMEOUT_SECONDS; attempt++)); do
    current_pid=$(/bin/launchctl print "${service_target}" 2>/dev/null | /usr/bin/awk '/^[[:space:]]*pid = / {print $3; exit}')
    if [[ -n "${current_pid}" && ( -z "${old_pid}" || "${current_pid}" != "${old_pid}" ) ]]; then
        if health_body=$(/usr/bin/curl --fail --silent --show-error --connect-timeout 2 --max-time 5 "${HEALTH_URL}" 2>/dev/null); then
            if printf '%s' "${health_body}" | /usr/bin/jq -e \
                '.status == "healthy" and .database == "connected"' >/dev/null; then
                new_pid="${current_pid}"
                break
            fi
        fi
    fi
    /bin/sleep 1
done

if [[ -z "${new_pid}" ]]; then
    echo "Hindsight did not become healthy within ${STARTUP_TIMEOUT_SECONDS} seconds" >&2
    exit 1
fi

if ! /usr/bin/tail -n "+${log_start_line}" "${SERVICE_LOG}" | /usr/bin/grep -Fq "${EXPECTED_CONFIG_LOG}"; then
    echo "Service restarted, but the new log does not confirm ${SERVICE_ENV}" >&2
    exit 1
fi

printf 'config_source=%s\n' "${SERVICE_ENV}"
printf 'old_pid=%s new_pid=%s\n' "${old_pid:-not-running}" "${new_pid}"
printf '%s' "${health_body}" | /usr/bin/jq '{status, database}'
