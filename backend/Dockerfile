FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# PostgreSQL 16 client (pg_dump/pg_restore) for backups. Debian bookworm ships 15, which can't
# dump a 16 server, so it comes from the PGDG apt repo. The repo's public signing key is kept in
# the repo (docker/pgdg.asc, fingerprint B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8) rather
# than downloaded from www.postgresql.org, whose outages broke builds; apt retries flaky fetches.
COPY docker/pgdg.asc /etc/apt/keyrings/pgdg.asc
RUN set -eux; \
    echo "deb [signed-by=/etc/apt/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends postgresql-client-16; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY alembic/ alembic/
COPY app/ app/
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
