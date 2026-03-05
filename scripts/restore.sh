#!/usr/bin/env bash
#
# Nova Emergency Restore Script
#
# Restores a database backup when the Recovery UI is unavailable.
# For normal operation, use the dashboard: /recovery
#
# Usage:
#   ./scripts/restore.sh                               # Lists available backups
#   ./scripts/restore.sh ./backups/nova-backup-*.tar.gz # Restore specific backup
#
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"

# If no argument, list available backups
if [ $# -eq 0 ]; then
  echo "Nova Backups"
  echo "============"
  echo ""
  if [ -d "$BACKUP_DIR" ] && ls "$BACKUP_DIR"/nova-backup-*.tar.gz 1>/dev/null 2>&1; then
    echo "Available backups (newest first):"
    echo ""
    ls -lhtr "$BACKUP_DIR"/nova-backup-*.tar.gz | awk '{print "  " $NF " (" $5 ")"}'
    echo ""
    echo "Usage: ./scripts/restore.sh <backup-file>"
  else
    echo "No backups found in ${BACKUP_DIR}/"
    echo "Create one with: ./scripts/backup.sh"
  fi
  exit 0
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Error: Backup file not found: $BACKUP_FILE"
  exit 1
fi

echo ""
echo "WARNING: This will overwrite your current Nova database!"
echo "  Backup: $BACKUP_FILE"
echo ""
read -p "Type YES to continue: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
  echo "Aborted."
  exit 1
fi

# Create temp directory
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo ""
echo "Extracting backup..."
tar -xzf "$BACKUP_FILE" -C "$TMPDIR"

if [ ! -f "${TMPDIR}/database.sql" ]; then
  echo "Error: Backup archive missing database.sql"
  exit 1
fi

echo "Restoring database..."
docker compose exec -T postgres psql -U nova nova --single-transaction \
  < "${TMPDIR}/database.sql"

echo ""
echo "Database restored. Restarting services..."
docker compose restart orchestrator memory-service llm-gateway chat-api

echo ""
echo "Restore complete. Nova should be back online shortly."
