#!/usr/bin/env python3
"""
Build a local SQLite database from the Spotify MPD JSON slices.

Usage (from repo root):
  # env from .env is optional; you can also export variables:
  # export MPD_DIR=./data/data
  # export MPD_SQLITE_PATH=./data/mpd.sqlite
  python tools/build_mpd_sqlite.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Use the same DB utilities as the app
from musiccrs.playlist_db import get_conn, build_from_mpd_folder

def main():
    load_dotenv()
    mpd_dir = Path(os.environ.get("MPD_DIR", "data/data")).resolve()
    db_path = Path(os.environ.get("MPD_SQLITE_PATH", "data/mpd.sqlite")).resolve()

    if not mpd_dir.exists():
        raise SystemExit(f"MPD_DIR does not exist: {mpd_dir}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(db_path)  # creates schema, does NOT seed the sample

    before = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    print(f"MPD source: {mpd_dir}")
    print(f"SQLite DB : {db_path}")
    print(f"Rows before: {before}")

    added = build_from_mpd_folder(mpd_dir, conn)

    after = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    print(f"Rows after : {after} (inserted ~{after - before})")

    # Optional optimizations
    conn.execute("ANALYZE;")
    conn.commit()
    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()
