"""Offline maintenance only. Stop the service before applying retention cleanup."""
import argparse
from contextlib import closing
from datetime import datetime,timedelta,timezone
import getpass
import json
from pathlib import Path
import re
import shutil
import sqlite3


def cleanup(data,database,hours,apply=False):
    if hours < 1:
        raise ValueError("retention hours must be at least one")
    data,database = Path(data).resolve(),Path(database).resolve()
    if not database.is_file() or not database.is_relative_to(data):
        raise ValueError("Database must exist within the managed data directory")
    cutoff = (datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        rows = connection.execute("""SELECT session_id FROM analysis_sessions
            WHERE status IN ('completed','failed','cancelled') AND completed_at < ?""",(cutoff,)).fetchall()
        removed = []
        for (identifier,) in rows:
            if not re.fullmatch(r"[a-f0-9]{32}",identifier):
                continue
            folder = data/identifier
            if folder.is_symlink() or not folder.resolve().is_relative_to(data):
                raise ValueError("Unsafe session directory; cleanup aborted")
            if apply:
                if folder.exists():
                    shutil.rmtree(folder)
                connection.execute("DELETE FROM analysis_sessions WHERE session_id=?",(identifier,))
            removed.append(identifier)
    return {"applied":apply,"eligible_sessions":removed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    password = sub.add_parser("password-hash")
    retain = sub.add_parser("cleanup")
    retain.add_argument("--data",type=Path,required=True)
    retain.add_argument("--database",type=Path,required=True)
    retain.add_argument("--hours",type=int,default=72)
    retain.add_argument("--apply",action="store_true")
    args = parser.parse_args()
    if args.command == "password-hash":
        from werkzeug.security import generate_password_hash
        first,second = getpass.getpass("New operator password: "),getpass.getpass("Repeat password: ")
        if first != second or len(first) < 16:
            raise SystemExit("Use matching passwords of at least 16 characters.")
        print(generate_password_hash(first))
    else:
        print(json.dumps(cleanup(args.data,args.database,args.hours,args.apply),indent=2))


if __name__ == "__main__":
    main()
