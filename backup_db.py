"""Consistent backup of the SQLite database (safe while the site is running).

    python backup_db.py              # writes DATA_DIR/backups/cards-YYYYmmdd-HHMMSS.db, keeps the newest 14

Run it daily from cron (see DEPLOY.md). Also copy the subjects folder, avatars and secret_key
if you want a complete backup of the site.
"""
import sqlite3
import sys
from datetime import datetime

import db

KEEP = 14


def main() -> None:
    backups = db.INSTANCE_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"cards-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(db.DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)                      # SQLite's online backup API
    src.close()
    dst.close()
    target.chmod(0o600)
    for old in sorted(backups.glob("cards-*.db"))[:-KEEP]:
        old.unlink()
    print("backup written:", target)


if __name__ == "__main__":
    sys.exit(main())
