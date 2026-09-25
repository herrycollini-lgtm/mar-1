"""Create a consistent SQLite backup of the Marè reservation database."""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SITE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("MARE_DB_PATH", str(SITE_DIR / "data" / "mare.sqlite3")))
BACKUP_DIR = Path(os.environ.get("MARE_BACKUP_DIR", str(SITE_DIR / "backups")))


def main():
    if not DB_PATH.is_file():
        print("Database non trovato: {}".format(DB_PATH), file=sys.stderr)
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y%m%d-%H%M%S")
    destination = BACKUP_DIR / "mare-{}.sqlite3".format(timestamp)
    suffix = 1
    while destination.exists():
        destination = BACKUP_DIR / "mare-{}-{}.sqlite3".format(timestamp, suffix)
        suffix += 1

    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as source:
            with sqlite3.connect(str(destination), timeout=30) as backup:
                source.backup(backup)
    except sqlite3.Error as error:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        print("Backup non riuscito: {}".format(error), file=sys.stderr)
        return 1

    print("Backup creato: {}".format(destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
