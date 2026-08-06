#!/usr/bin/env python3
"""
Automated PostgreSQL Database Backup Script with Retention Cleanup.
Usage: python scripts/backup_db.py [--retention-days 14]
"""

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "scripts" / "backups"


def run_backup(retention_days: int = 14):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"db_backup_{timestamp}.sql"

    db_url = os.getenv("DATABASE_URL_SYNC", "postgresql+psycopg2://postgres:postgres@localhost:5432/movie_reservation_db")
    print(f"📦 Starting PostgreSQL backup to: {backup_file}...")

    # Extract connection details
    try:
        # e.g., postgresql+psycopg2://user:password@host:port/dbname
        clean_url = db_url.replace("postgresql+psycopg2://", "").replace("postgresql://", "")
        auth_part, db_part = clean_url.split("@")
        user_pass = auth_part.split(":")
        user = user_pass[0]
        password = user_pass[1] if len(user_pass) > 1 else ""

        host_port_db = db_part.split("/")
        host_port = host_port_db[0].split(":")
        host = host_port[0]
        port = host_port[1] if len(host_port) > 1 else "5432"
        dbname = host_port_db[1]

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        cmd = [
            "pg_dump",
            "-h", host,
            "-p", port,
            "-U", user,
            "-d", dbname,
            "-F", "p",
            "-f", str(backup_file),
        ]

        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if res.returncode == 0 and backup_file.exists() and backup_file.stat().st_size > 0:
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            print(f"✅ Backup successful! Size: {size_mb:.2f} MB")
        else:
            print(f"⚠️ pg_dump warning/notice: {res.stderr}")
            print(f"📄 Backup created at: {backup_file}")
    except Exception as e:
        print(f"❌ Backup failed: {e}")

    # Retention Cleanup: Delete backups older than retention_days
    print(f"🧹 Cleaning up backups older than {retention_days} days...")
    now = datetime.now()
    deleted_count = 0
    for file in BACKUP_DIR.glob("*.sql"):
        try:
            mtime = datetime.fromtimestamp(file.stat().st_mtime)
            if (now - mtime).days > retention_days:
                file.unlink()
                deleted_count += 1
                print(f"  🗑️ Deleted old backup: {file.name}")
        except Exception as err:
            print(f"  ⚠️ Could not delete {file.name}: {err}")

    print(f"✨ Cleanup finished. Deleted {deleted_count} old file(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PostgreSQL Automated Backup Script")
    parser.add_argument("--retention-days", type=int, default=14, help="Days to retain backup files")
    args = parser.parse_args()
    run_backup(args.retention_days)
