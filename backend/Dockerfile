FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# PostgreSQL 16 client (pg_dump/pg_restore) for backups. Debian bookworm ships 15, which can't
# dump a 16 server, so it comes from the PGDG apt repo. The slim image has no curl, so Python
# fetches the repo's signing key; apt reads the ASCII-armoured .asc via signed-by.
RUN set -eux; \
    install -d -m 0755 /etc/apt/keyrings; \
    python -c "import urllib.request; urllib.request.urlretrieve('https://www.postgresql.org/media/keys/ACCC4CF8.asc', '/etc/apt/keyrings/pgdg.asc')"; \
    echo "deb [signed-by=/etc/apt/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY alembic/ alembic/
COPY app/ app/
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
