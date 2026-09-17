FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build tools for any wheels that need compiling (argon2 / asyncpg have wheels,
# but keep this for safety on slim).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# setuptools discovers the `app` package, so the source must be present before
# the install step (editable install needs the package dir to exist).
COPY . .
RUN pip install --upgrade pip && pip install .

# SECURITY (2026-09-14): run uvicorn as an unprivileged user, not root, so a
# future RCE does not land as root. /data is the attachments volume mountpoint;
# existing volumes are chowned separately (see deploy notes) since a non-empty
# named volume keeps its own ownership over the image's.
RUN useradd -m -u 1000 appuser \
    && mkdir -p /data/attachments \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
