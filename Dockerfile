# Build context: project root (docker-compose: context .)
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-server.txt

COPY main.py antiban_core.py celery_worker.py ./
COPY schema_pg.sql ./
COPY migrations ./migrations
COPY static ./static
COPY app ./app

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

CMD ["python", "-m", "app.main", "--no-browser"]
