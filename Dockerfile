FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    XDG_CONFIG_HOME=/tmp/.config \
    YOLO_CONFIG_DIR=/tmp/Ultralytics \
    TORCH_HOME=/tmp/torch

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /app --no-create-home app

COPY requirements-yolo.txt ./
RUN pip install --no-cache-dir -r requirements-yolo.txt

COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini run.py ./
COPY --chown=app:app deploy/container-models ./models
RUN mkdir -p /app/evidence && chown app:app /app/evidence

USER app

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD ["python", "-m", "app.container_healthcheck"]

ENTRYPOINT ["tini", "--", "python", "-m", "app.container_entrypoint"]
CMD ["python", "run.py"]
