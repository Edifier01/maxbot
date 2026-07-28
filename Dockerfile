FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-scale.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-scale.txt || true

COPY main.py celery_worker.py schema_pg.sql ./
COPY static ./static

ENV MAX_HOST=0.0.0.0
ENV MAX_PORT=8765
ENV PYTHONUNBUFFERED=1

EXPOSE 8765

VOLUME ["/app/data"]

CMD ["python", "main.py", "--no-browser"]
