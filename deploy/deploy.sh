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
if [[ "${RUN_DATABASE_MIGRATIONS:-}" =~ ^(1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn])$ ]] || \
   grep -Eiq '^[[:space:]]*RUN_DATABASE_MIGRATIONS[[:space:]]*=[[:space:]]*(1|true|yes|on)[[:space:]]*(#.*)?$' "${ENV_FILE}"; then
  echo "production deployment refuses automatic database migrations; finish the verified offline migration first" >&2
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
if [[ "${action}" == "up" || "${action}" == "pull-up" ]]; then
  # The operator must review a local acceptance record before deployment.
  if [[ -z "${AIYOLO_LOCAL_ACCEPTANCE_RECORD:-}" || ! -s "${AIYOLO_LOCAL_ACCEPTANCE_RECORD}" ]]; then
    echo "finish local acceptance first; set AIYOLO_LOCAL_ACCEPTANCE_RECORD to the reviewed record" >&2
    exit 1
  fi
fi
case "${action}" in
  config)
    compose config --quiet
    echo "production configuration is valid"
    ;;
  up)
    compose config --quiet
    compose build --pull video-service model-converter
    compose up -d --wait --wait-timeout 300
    compose ps
    ;;
  pull-up)
    compose config --quiet
    compose pull video-service model-converter
    compose up -d --no-build --wait --wait-timeout 300
    compose ps
    ;;
  status)
    compose ps
    ;;
  logs)
    compose logs --tail 200 -f "${2:-video-service}"
    ;;
  smoke)
    compose exec -T video-service python -m app.container_healthcheck
    compose exec -T video-service python -c 'from app.alert_evidence import AlertEvidenceStore; from app.config import settings; store=AlertEvidenceStore.from_settings(settings); store.validate(); print("MINIO_OK", settings.minio_bucket)'
    compose exec -T video-service python -c 'import os,urllib.request; name=os.environ.get("CONVERSION_REMOTE_TOKEN_ENV","AIYOLO_REMOTE_CONVERSION_TOKEN"); url=os.environ["CONVERSION_REMOTE_ENDPOINT"].rstrip("/")+"/v1/health"; request=urllib.request.Request(url,headers={"Authorization":"Bearer "+os.environ[name]}); response=urllib.request.urlopen(request,timeout=10); print("CONVERTER_OK",response.status)'
    ;;
  backup-db)
    umask 077
    backup_dir="${PROJECT_ROOT}/backups"
    mkdir -p "${backup_dir}"
    backup_file="${backup_dir}/postgres-$(date -u +%Y%m%dT%H%M%SZ).dump"
    if ! command -v pg_dump >/dev/null 2>&1; then
      echo "pg_dump is required for cloud database backups; install PostgreSQL client tools first" >&2
      exit 1
    fi
    database_url="${DATABASE_URL:-}"
    if [[ -z "${database_url}" ]]; then
      database_url="$(sed -n 's/^DATABASE_URL=//p' "${ENV_FILE}" | head -n 1)"
    fi
    pg_dump_url="${database_url:?DATABASE_URL is required in the production env file}"
    pg_dump_url="${pg_dump_url/postgresql+psycopg:/postgresql:}"
    # libpq accepts a connection URI in PGDATABASE; never put credentials in argv.
    PGDATABASE="${pg_dump_url}" pg_dump --no-password --format=custom --file="${backup_file}"
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
  up                 build/start after reviewed local acceptance
  pull-up            pull/start after reviewed local acceptance
  status             show container and health state
  logs [service]     follow recent logs (default: video-service)
  smoke              verify application, MinIO and converter connectivity
  backup-db          create a PostgreSQL custom-format backup in backups/
  stop               stop containers without deleting persistent volumes

up/pull-up require AIYOLO_LOCAL_ACCEPTANCE_RECORD. Old media containers are not
automatically removed: follow docs/media-retirement-upgrade.md after approval.
EOF
    ;;
esac
