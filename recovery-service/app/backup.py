"""Backup and restore operations via pg_dump / pg_restore."""

import asyncio
import gzip
import logging
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

logger = logging.getLogger("nova.recovery.backup")


def _backup_dir() -> Path:
    d = settings.backup_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_backups() -> list[dict]:
    """List available backups sorted newest-first."""
    d = _backup_dir()
    backups = []
    for f in sorted(d.glob("nova-backup-*.tar.gz"), reverse=True):
        stat = f.stat()
        backups.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return backups


async def create_backup() -> dict:
    """Create a backup: pg_dump + config files → single .tar.gz."""
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"nova-backup-{timestamp}.tar.gz"
    outpath = _backup_dir() / filename

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # pg_dump
        sql_path = tmp / "database.sql"
        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            "-h", settings.pg_host,
            "-p", str(settings.pg_port),
            "-U", settings.pg_user,
            "-d", settings.pg_database,
            "--no-owner",
            "--no-acl",
            "-f", str(sql_path),
            env={**os.environ, "PGPASSWORD": settings.pg_password},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {stderr.decode()}")

        # Bundle into tar.gz
        with tarfile.open(outpath, "w:gz") as tar:
            tar.add(sql_path, arcname="database.sql")

        logger.info("Backup created: %s (%.1f MB)", filename, outpath.stat().st_size / 1_048_576)

    # Prune old backups
    _prune_old_backups()

    stat = outpath.stat()
    return {
        "filename": filename,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


async def restore_backup(filename: str) -> dict:
    """Restore database from a backup .tar.gz file."""
    backup_path = _backup_dir() / filename
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {filename}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Extract
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(tmp, filter="data")

        sql_path = tmp / "database.sql"
        if not sql_path.exists():
            raise RuntimeError("Backup archive missing database.sql")

        # Drop and recreate all tables by restoring into a clean state
        proc = await asyncio.create_subprocess_exec(
            "psql",
            "-h", settings.pg_host,
            "-p", str(settings.pg_port),
            "-U", settings.pg_user,
            "-d", settings.pg_database,
            "-f", str(sql_path),
            "--single-transaction",
            env={**os.environ, "PGPASSWORD": settings.pg_password},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Database restore failed: {stderr.decode()}")

    logger.info("Restored from backup: %s", filename)
    return {"filename": filename, "restored": True}


def delete_backup(filename: str) -> dict:
    """Delete a specific backup file."""
    backup_path = _backup_dir() / filename
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {filename}")
    # Safety: only delete files matching our naming pattern
    if not filename.startswith("nova-backup-") or not filename.endswith(".tar.gz"):
        raise ValueError("Invalid backup filename")
    backup_path.unlink()
    logger.info("Deleted backup: %s", filename)
    return {"filename": filename, "deleted": True}


def list_checkpoints() -> list[dict]:
    """List automatic checkpoint backups sorted newest-first."""
    d = _backup_dir()
    checkpoints = []
    for f in sorted(d.glob("nova-checkpoint-*.tar.gz"), reverse=True):
        stat = f.stat()
        checkpoints.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return checkpoints


async def create_checkpoint() -> dict:
    """Create an automatic checkpoint backup (same as manual but different prefix)."""
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"nova-checkpoint-{timestamp}.tar.gz"
    outpath = _backup_dir() / filename

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        sql_path = tmp / "database.sql"
        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            "-h", settings.pg_host,
            "-p", str(settings.pg_port),
            "-U", settings.pg_user,
            "-d", settings.pg_database,
            "--no-owner",
            "--no-acl",
            "-f", str(sql_path),
            env={**os.environ, "PGPASSWORD": settings.pg_password},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {stderr.decode()}")

        with tarfile.open(outpath, "w:gz") as tar:
            tar.add(sql_path, arcname="database.sql")

        logger.info("Checkpoint created: %s (%.1f MB)", filename, outpath.stat().st_size / 1_048_576)

    stat = outpath.stat()
    return {
        "filename": filename,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def prune_checkpoints(max_keep: int) -> int:
    """Delete oldest checkpoints beyond the retention limit. Returns number pruned."""
    d = _backup_dir()
    checkpoints = sorted(d.glob("nova-checkpoint-*.tar.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    pruned = 0
    for f in checkpoints[max_keep:]:
        f.unlink()
        logger.info("Pruned checkpoint: %s", f.name)
        pruned += 1
    return pruned


def _prune_old_backups():
    """Remove backups older than retention period."""
    if settings.backup_retain_days <= 0:
        return
    d = _backup_dir()
    cutoff = datetime.now(tz=timezone.utc).timestamp() - (settings.backup_retain_days * 86400)
    for f in d.glob("nova-backup-*.tar.gz"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            logger.info("Pruned old backup: %s", f.name)
