#!/usr/bin/env bash
# ============================================================
# GameHub — Production Database Backup Script
# ============================================================
# Usage (from host):
#   docker compose -f docker-compose.prod.yml exec postgres /backups/backup_db.sh
#
# Or copy this script into the postgres container and run:
#   docker cp scripts/backup_db.sh gamehub-postgres:/backups/backup_db.sh
#   docker exec gamehub-postgres bash /backups/backup_db.sh
#
# Backups are written to /backups/ (the mounted db_backups volume).
# Files older than RETENTION_DAYS are automatically purged.
# ============================================================

set -euo pipefail

# ----- Configuration (override via environment) -----
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGDATABASE="${PGDATABASE:-gamehub}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# ----- Derived Values -----
TIMESTAMP="$(date +%Y-%m-%dT%H-%M-%S)"
BACKUP_FILE="${BACKUP_DIR}/gamehub_backup_${TIMESTAMP}.dump"

echo "============================================"
echo " GameHub Database Backup"
echo " Host:      ${PGHOST}:${PGPORT}"
echo " Database:  ${PGDATABASE}"
echo " Output:    ${BACKUP_FILE}"
echo " Retention: ${RETENTION_DAYS} days"
echo "============================================"

# ----- Ensure backup directory exists -----
mkdir -p "${BACKUP_DIR}"

# ----- Execute pg_dump -----
echo "[$(date)] Starting backup..."

pg_dump \
    --host="${PGHOST}" \
    --port="${PGPORT}" \
    --username="${PGUSER}" \
    --dbname="${PGDATABASE}" \
    --format=custom \
    --compress=6 \
    --verbose \
    --file="${BACKUP_FILE}"

if [ $? -eq 0 ]; then
    FILESIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
    echo "[$(date)] ✓ Backup completed successfully: ${BACKUP_FILE} (${FILESIZE})"
else
    echo "[$(date)] ✗ Backup FAILED!" >&2
    exit 1
fi

# ----- Cleanup old backups -----
echo "[$(date)] Cleaning up backups older than ${RETENTION_DAYS} days..."
DELETED=$(find "${BACKUP_DIR}" -name "gamehub_backup_*.dump" -type f -mtime +"${RETENTION_DAYS}" -print -delete | wc -l)
echo "[$(date)] ✓ Purged ${DELETED} old backup(s)."

echo "============================================"
echo " Backup complete."
echo "============================================"
