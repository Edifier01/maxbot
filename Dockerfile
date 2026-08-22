# Build context: project root (docker-compose: context .)
# Digest обновлять осознанно после CI smoke.
FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock requirements-server.lock ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels \
    -r requirements.lock -r requirements-server.lock

FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS runtime

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels \
    && groupadd --gid 10001 maxsender \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin maxsender \
    && mkdir -p /app/data \
    && chown -R 10001:10001 /app

COPY --chown=10001:10001 main.py antiban_core.py celery_worker.py ./
COPY --chown=10001:10001 schema_pg.sql ./
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 static ./static
COPY --chown=10001:10001 app ./app

ENV MAX_HOST=0.0.0.0
ENV MAX_PORT=8765
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import json,sys,urllib.request;\
r=urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=4);\
d=json.loads(r.read());sys.exit(0 if d.get('db_ok') else 1)"

VOLUME ["/app/data"]

USER 10001:10001

CMD ["python", "-m", "app.main", "--no-browser"]
