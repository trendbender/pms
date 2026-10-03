#!/usr/bin/env bash
# Daily Postgres dump for PMS, with retention. Meant to run from cron on the
# production host:
#
#   30 3 * * * /srv/projects/pms/deploy/backup-db.sh >> /var/log/pms-backup.log 2>&1
#
# Env overrides: BACKUP_DIR (default /srv/backups/pms), KEEP_DAYS (default 14),
# COMPOSE_FILE (default docker-compose.prod.yml).
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/srv/projects/pms}"
BACKUP_DIR="${BACKUP_DIR:-/srv/backups/pms}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

cd "$PROJECT_DIR"

# Credentials live in the prod .env only — never on the command line.
POSTGRES_USER="$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)"
: "${POSTGRES_USER:?POSTGRES_USER missing from .env}"
: "${POSTGRES_DB:?POSTGRES_DB missing from .env}"

mkdir -p "$BACKUP_DIR"
stamp="$(date +%F-%H%M)"
target="$BACKUP_DIR/pms-$stamp.sql.gz"
tmp="$target.part"

# pg_dump straight out of the container; the .part name means an interrupted run
# never looks like a finished backup.
docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip -9 > "$tmp"

# A dump that is empty or not valid gzip is a failed backup — keep the old ones.
if [ ! -s "$tmp" ] || ! gzip -t "$tmp" 2>/dev/null; then
    rm -f "$tmp"
    echo "$(date -Is) BACKUP FAILED: dump is empty or corrupt" >&2
    exit 1
fi
mv "$tmp" "$target"
size="$(du -h "$target" | cut -f1)"
echo "$(date -Is) backup ok: $target ($size)"

# Attachments live on a docker volume, not in the database — a dump alone would
# restore tasks with dead file links, so they are archived alongside it.
att_target="$BACKUP_DIR/pms-attachments-$stamp.tar.gz"
att_tmp="$att_target.part"
if docker compose -f "$COMPOSE_FILE" exec -T backend \
        tar -czf - -C /data attachments > "$att_tmp" 2>/dev/null \
   && [ -s "$att_tmp" ] && gzip -t "$att_tmp" 2>/dev/null; then
    mv "$att_tmp" "$att_target"
    echo "$(date -Is) attachments ok: $att_target ($(du -h "$att_target" | cut -f1))"
else
    rm -f "$att_tmp"
    echo "$(date -Is) WARNING: attachments archive failed (db dump is fine)" >&2
fi

# Rotate only after a verified new dump, so a broken run can never leave us with
# nothing.
deleted="$(find "$BACKUP_DIR" -maxdepth 1 \( -name 'pms-*.sql.gz' -o -name 'pms-attachments-*.tar.gz' \) -mtime "+$KEEP_DAYS" -print -delete | wc -l | tr -d ' ')"
kept="$(find "$BACKUP_DIR" -maxdepth 1 -name 'pms-*.sql.gz' | wc -l | tr -d ' ')"
echo "$(date -Is) retention ${KEEP_DAYS}d: removed $deleted old file(s), $kept dump(s) kept"
