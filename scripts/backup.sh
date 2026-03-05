#!/usr/bin/env bash
#
# Nova Emergency Backup Script
#
# Creates a database backup when the Recovery UI is unavailable.
# For normal operation, use the dashboard: Settings > Backups or /recovery
#
# Usage:
#   ./scripts/backup.sh                  # Backup to ./backups/
#   BACKUP_DIR=/mnt/nas ./scripts/backup.sh  # Custom location
#
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date -u +%Y-%m-%d_%H-%M-%S)
FILENAME="nova-backup-${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "Creating Nova backup..."
echo "  Output: ${BACKUP_DIR}/${FILENAME}"

# Create temp directory for dump
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Dump database
echo "  Dumping database..."
docker compose exec -T postgres pg_dump -U nova nova --no-owner --no-acl \
  > "${TMPDIR}/database.sql"

# Bundle into tar.gz
echo "  Packaging..."
tar -czf "${BACKUP_DIR}/${FILENAME}" -C "$TMPDIR" database.sql

SIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo ""
echo "Backup complete: ${BACKUP_DIR}/${FILENAME} (${SIZE})"
echo ""
echo "To restore: ./scripts/restore.sh ${BACKUP_DIR}/${FILENAME}"
