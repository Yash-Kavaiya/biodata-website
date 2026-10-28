FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY run.py .

# Run as an unprivileged user; uploads and the JSON database live in /app/data
RUN useradd --create-home appuser \
    && mkdir -p /app/data/uploads /app/data/db \
    && chown -R appuser /app/data
USER appuser

ENV UPLOAD_DIR=/app/data/uploads \
    DB_DIR=/app/data/db
VOLUME ["/app/data"]

# Cloud Run sets PORT; default to 8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8080\")}/api/health')"
CMD exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}
