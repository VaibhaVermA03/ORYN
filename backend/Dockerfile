FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Run as an unprivileged user; storage and temp directories are the only writable paths.
RUN useradd --create-home --uid 10001 oryn \
    && mkdir -p /var/data/storage /var/data/tmp \
    && chown -R oryn:oryn /app /var/data
USER oryn

ENV STORAGE_DIR=/var/data/storage \
    TEMP_DIR=/var/data/tmp \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health/live',timeout=3)" || exit 1

# Migrations are an explicit step (`alembic upgrade head`), never run implicitly at startup.
# --proxy-headers lets the app see the client IP and scheme behind Render's/Docker's proxy.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
