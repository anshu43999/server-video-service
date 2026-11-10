#!/bin/sh
# Run only from a clean checkout of an approved, pushed commit.
set -eu
expected=${1:?full commit SHA required}
tag=${2:?new image tag required}
output=${3:?absolute evidence directory required}
case "$output" in /*) ;; *) echo 'Absolute evidence directory required' >&2; exit 2;; esac
test -d "$output"
test "$(git rev-parse HEAD)" = "$expected"
test -z "$(git status --porcelain --untracked-files=all --ignored)"
test ! -e .env
for file in Dockerfile.converter constraints-converter.txt .dockerignore tools/check_converter_runtime.py tools/check_cpu_runtime.py tools/conversion_worker.py; do
    git ls-files --error-unmatch "$file" >/dev/null
done
if docker image inspect "$tag" >/dev/null 2>&1; then
    echo 'Refusing to overwrite existing image tag' >&2
    exit 3
fi
test ! -e "$output/image.id"
git rev-parse HEAD > "$output/source-commit.txt"
git rev-parse 'HEAD^{tree}' > "$output/source-tree.txt"
sha256sum Dockerfile.converter .dockerignore constraints-converter.txt requirements*.txt tools/check_converter_runtime.py tools/check_cpu_runtime.py tools/conversion_worker.py tools/build_converter_release.sh > "$output/build-inputs.sha256"
docker version > "$output/docker-version.txt"
uname -m > "$output/platform.txt"
date -u +%FT%TZ > "$output/build.started-at.txt"
DOCKER_BUILDKIT=1 docker build --progress=plain --platform=linux/amd64 \
    --label "org.opencontainers.image.revision=$expected" \
    --label org.opencontainers.image.source=https://github.com/anshu43999/server-video-service \
    --iidfile "$output/image.id" -t "$tag" -f Dockerfile.converter .
test -z "$(git status --porcelain --untracked-files=all --ignored)"
date -u +%FT%TZ > "$output/build.finished-at.txt"
docker image inspect "$tag" > "$output/image-inspect.json"
docker image inspect python:3.11-slim-bookworm > "$output/base-image-inspect.json"
