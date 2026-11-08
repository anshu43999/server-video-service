FROM node:22.22.0-bookworm-slim AS admin-build
WORKDIR /admin-web
COPY admin-web/package.json admin-web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY admin-web/ ./
RUN npm run test && npm run build && npm run build:preview

FROM python:3.11-slim-bookworm AS apk-tools
COPY tools/install_android_verifier.py /tmp/install_android_verifier.py
RUN test "$(dpkg --print-architecture)" = amd64 \
    && python /tmp/install_android_verifier.py --destination /opt/android/build-tools/36.0.0

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    ADMIN_FRONTEND_MODE=vue \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    XDG_CONFIG_HOME=/tmp/.config \
    YOLO_CONFIG_DIR=/tmp/Ultralytics \
    TORCH_HOME=/tmp/torch \
    YOLO_DEVICE=cpu \
    CUDA_VISIBLE_DEVICES="" \
    JAX_PLATFORMS=cpu \
    PIP_CONSTRAINT=/app/constraints-cpu.txt \
    PIP_FIND_LINKS="https://download.pytorch.org/whl/cpu/torch/ https://download.pytorch.org/whl/cpu/torchvision/"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 tini openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /app --no-create-home app

COPY requirements.txt requirements-yolo.txt requirements-verifier.txt ./
COPY requirements-cpu.txt constraints-cpu.txt ./
COPY tools/check_cpu_runtime.py ./tools/check_cpu_runtime.py
RUN pip install --no-cache-dir -r requirements-yolo.txt -r requirements-verifier.txt \
    && pip check \
    && python tools/check_cpu_runtime.py

COPY --chown=app:app app ./app
COPY --from=admin-build --chown=app:app /admin-web/dist ./admin-web/dist
COPY --from=admin-build --chown=app:app /admin-web/dist-preview ./admin-web/dist-preview
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini run.py ./
COPY --chown=app:app tools/conversion_worker.py ./tools/conversion_worker.py
COPY --chown=app:app tools/check_app_update_runtime.py ./tools/check_app_update_runtime.py
COPY --from=apk-tools /opt/android/build-tools/36.0.0 /opt/android/build-tools/36.0.0
ENV APP_APK_AAPT2_PATH=/opt/android/build-tools/36.0.0/aapt2 \
    APP_APK_JAVA_PATH=/usr/bin/java \
    APP_APK_APKSIGNER_JAR_PATH=/opt/android/build-tools/36.0.0/lib/apksigner.jar \
    APP_APK_EVIDENCE_ROOT=/app/evidence/app-apk-verification \
    APP_APK_STAGING_ROOT=/tmp/app-apk-verification \
    APP_APK_EXTERNAL_ROOT=/app/app-update-data/external \
    APP_APK_UPLOAD_ROOT=/app/app-update-data/uploads
COPY --chown=app:app deploy/container-models ./models
RUN mkdir -p /app/evidence/app-apk-verification /app/calibration \
        /app/app-update-data/external /app/app-update-data/uploads /tmp/app-apk-verification \
    && chown -R app:app /app/evidence /app/calibration /app/app-update-data /tmp/app-apk-verification

USER app
RUN python /app/tools/check_app_update_runtime.py --tools-only

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD ["python", "-m", "app.container_healthcheck"]

ENTRYPOINT ["tini", "--", "python", "-m", "app.container_entrypoint"]
CMD ["python", "run.py"]
