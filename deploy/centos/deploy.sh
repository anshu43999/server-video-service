#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${AIYOLO_ENV_FILE:-${SCRIPT_DIR}/.env}"
COMPOSE_FILE="${PROJECT_ROOT}/compose.centos.yml"

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
  echo "copy deploy/centos/.env.example to deploy/centos/.env and replace CHANGE_ME values" >&2
  exit 1
fi
if grep -q 'CHANGE_ME' "${ENV_FILE}"; then
  echo "the environment file still contains CHANGE_ME placeholders" >&2
  exit 1
fi

compose() {
  docker compose \
    --project-directory "${PROJECT_ROOT}" \
    --env-file "${ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
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
    compose build --pull video-service
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
Usage: bash deploy/centos/deploy.sh <command>

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
