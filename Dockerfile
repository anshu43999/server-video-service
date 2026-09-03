FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-yolo.txt .
RUN pip install --no-cache-dir -r requirements-yolo.txt
COPY app app
COPY run.py .
COPY .env.example .

EXPOSE 8080
CMD ["python", "run.py"]
