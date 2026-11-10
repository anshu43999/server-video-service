#!/bin/sh
# M32-T34: build only from a clean checkout of an approved, pushed commit.
set -eu
expected=${1:?full commit SHA required}
tag=${2:?new image tag required}
output=${3:?absolute evidence directory required}
case "$expected" in *[!0-9a-f]*|'') exit 2;; esac
test "${#expected}" -eq 40
case "$output" in /*) ;; *) echo 'Absolute evidence directory required' >&2; exit 2;; esac
test -d "$output"
test ! -L "$output"
test "$(git rev-parse HEAD)" = "$expected"
test -z "$(git status --porcelain --untracked-files=all --ignored)"
test ! -e .env
test ! -e admin-web/dist
test ! -e admin-web/dist-preview
for file in Dockerfile .dockerignore admin-web/package.json admin-web/package-lock.json tools/build_video_release.sh tools/check_cpu_runtime.py tools/install_android_verifier.py tools/check_app_update_runtime.py tools/conversion_worker.py; do
    git ls-files --error-unmatch "$file" >/dev/null
done
docker info >/dev/null
if docker image inspect "$tag" >/dev/null 2>&1; then
    echo 'Refusing to overwrite existing image tag' >&2
    exit 3
fi
test ! -e "$output/image.id"
git rev-parse HEAD > "$output/source-commit.txt"
git rev-parse 'HEAD^{tree}' > "$output/source-tree.txt"
sha256sum Dockerfile .dockerignore requirements*.txt constraints-cpu.txt admin-web/package.json admin-web/package-lock.json tools/build_video_release.sh tools/check_cpu_runtime.py tools/install_android_verifier.py tools/check_app_update_runtime.py tools/conversion_worker.py > "$output/build-inputs.sha256"
docker version > "$output/docker-version.txt"
uname -m > "$output/platform.txt"
date -u +%FT%TZ > "$output/build.started-at.txt"
DOCKER_BUILDKIT=1 docker build --progress=plain --platform=linux/amd64 \
    --label "org.opencontainers.image.revision=$expected" \
    --label org.opencontainers.image.source=https://github.com/anshu43999/server-video-service \
    --iidfile "$output/image.id" -t "$tag" -f Dockerfile .
test -z "$(git status --porcelain --untracked-files=all --ignored)"
date -u +%FT%TZ > "$output/build.finished-at.txt"
docker image inspect "$tag" > "$output/image-inspect.json"
docker image inspect python:3.11-slim-bookworm node:22.22.0-bookworm-slim > "$output/base-image-inspect.json"
