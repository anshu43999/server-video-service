#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${AIYOLO_ENV_FILE:-${PROJECT_ROOT}/.env}"
COMPOSE_FILE="${PROJECT_ROOT}/compose.yml"
COMPOSE_OVERRIDE_LIST="${AIYOLO_COMPOSE_OVERRIDE_LIST:-/etc/aiyolo/compose-overrides.list}"

COMPOSE_FILES=("${COMPOSE_FILE}")
if [[ -f "${COMPOSE_OVERRIDE_LIST}" ]]; then
  while IFS= read -r override_file || [[ -n "${override_file}" ]]; do
    override_file="${override_file%$'\r'}"
    [[ -z "${override_file}" || "${override_file}" == \#* ]] && continue
    if [[ "${override_file}" != /* ]]; then
      echo "Compose override paths must be absolute: ${override_file}" >&2
      exit 1
    fi
    if [[ ! -f "${override_file}" ]]; then
      echo "missing Compose override file: ${override_file}" >&2
      exit 1
    fi
    COMPOSE_FILES+=("${override_file}")
  done < "${COMPOSE_OVERRIDE_LIST}"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not available on PATH" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "the Docker Compose plugin is required" >&2
  exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "missing environment file: ${ENV_FILE}" >&2
  echo "copy .env.example to .env and replace CHANGE_ME values" >&2
  exit 1
fi
if grep -q 'CHANGE_ME' "${ENV_FILE}"; then
  echo "the environment file still contains CHANGE_ME placeholders" >&2
  exit 1
fi
if grep -Eq '^[[:space:]]*(ADMIN_TOKEN|MOBILE_TOKEN)[[:space:]]*=' "${ENV_FILE}"; then
  echo "ADMIN_TOKEN and MOBILE_TOKEN are development-only and must be removed from the production environment file" >&2
  exit 1
fi

compose() {
  local compose_files=()
  local compose_file
  for compose_file in "${COMPOSE_FILES[@]}"; do
    compose_files+=( -f "${compose_file}" )
  done
  docker compose \
    --project-directory "${PROJECT_ROOT}" \
    --env-file "${ENV_FILE}" \
    "${compose_files[@]}" \
    "$@"
}

action="${1:-help}"
case "${action}" in
  config)
    compose config --quiet
    echo "production configuration is valid"
    ;;
  up)
    compose config --quiet
    compose build --pull video-service model-converter
    compose up -d --remove-orphans
    compose ps
    ;;
  status)
    compose ps
    ;;
  logs)
    compose logs --tail 200 -f "${2:-video-service}"
    ;;
  backup-db)
    backup_dir="${PROJECT_ROOT}/backups"
    mkdir -p "${backup_dir}"
    backup_file="${backup_dir}/postgres-$(date -u +%Y%m%dT%H%M%SZ).dump"
    compose exec -T postgres sh -c \
      'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"${backup_file}"
    echo "database backup created: ${backup_file}"
    ;;
  stop)
    compose stop
    ;;
  help|*)
    cat <<'EOF'
Usage: bash deploy/deploy.sh <command>

Commands:
  config             validate Compose and required environment values
  up                 build and start the production stack
  status             show container and health state
  logs [service]     follow recent logs (default: video-service)
  backup-db          create a PostgreSQL custom-format backup in backups/
  stop               stop containers without deleting persistent volumes
EOF
    ;;
esac
