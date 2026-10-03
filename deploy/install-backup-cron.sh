#!/usr/bin/env bash
# Install (or refresh) the daily backup cron entry on the production host.
# Idempotent: an existing backup-db.sh line is replaced, not duplicated.
set -euo pipefail

SCRIPT="${SCRIPT:-/srv/projects/pms/deploy/backup-db.sh}"
LOG="${LOG:-/var/log/pms-backup.log}"
SCHEDULE="${SCHEDULE:-30 3 * * *}"

[ -x "$SCRIPT" ] || { echo "not executable: $SCRIPT" >&2; exit 1; }

{ crontab -l 2>/dev/null | grep -v 'backup-db.sh' || true; echo "$SCHEDULE $SCRIPT >> $LOG 2>&1"; } | crontab -

echo "cron now:"
crontab -l | grep backup-db.sh
