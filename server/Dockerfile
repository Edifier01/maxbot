# Build context: корень репозитория (docker-compose: context ..)
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-scale.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-scale.txt || true

COPY main.py antiban_core.py celery_worker.py schema_pg.sql ./
COPY static ./static
COPY server/__init__.py ./server/__init__.py
COPY server/app ./server/app

ENV MAX_HOST=0.0.0.0
ENV MAX_PORT=8765
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8765

VOLUME ["/app/data"]

CMD ["python", "-m", "server.app.main", "--no-browser"]
