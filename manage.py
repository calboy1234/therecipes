#!/usr/bin/env python3
"""
manage.py — TheRecipes database management CLI

Usage:
    python manage.py initdb     Create tables if they don't exist (safe on existing DB)
    python manage.py backup     Copy DB to a timestamped backup file
    python manage.py status     Show table info, row counts, schema version

Environment:
    DB_PATH      Override the database path (default: /data/database/therecipes.db)
    UPLOAD_DIR   Override the image upload directory (default: /data/uploads/images)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

DB_PATH    = os.environ.get("DB_PATH",    "/data/database/therecipes.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads/images")


# ── DB connection ─────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_initdb(args):
    """
    Create all tables if they don't exist.
    Safe to run against an existing database — nothing is dropped or overwritten.
    Also creates the image upload directory if it doesn't already exist.
    """
    # Ensure the upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    print(f"✓  Upload directory ready  : {UPLOAD_DIR}")

    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS recipes (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        title             TEXT,
        original_author   TEXT,
        recipe_submitter  TEXT,
        description       TEXT,
        serving_size      TEXT,
        ingredients       TEXT,
        instructions      TEXT,
        dish_category     TEXT,
        image_path        TEXT,
        image_hash        TEXT,
        created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
        is_deleted        INTEGER NOT NULL DEFAULT 0
    )
    """)

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipes_category  ON recipes(dish_category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipes_submitter ON recipes(recipe_submitter)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipes_deleted   ON recipes(is_deleted)")

    conn.commit()
    conn.close()

    print(f"✓  Database initialised at : {DB_PATH}")


def cmd_backup(args):
    """
    Copy the live database to a timestamped backup file in the same directory.
    Uses SQLite's built-in backup API — safe to run while the app is running.
    """
    if not os.path.isfile(DB_PATH):
        print(f"✗  No database found at: {DB_PATH}")
        sys.exit(1)

    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir  = os.path.dirname(DB_PATH)
    backup_path = os.path.join(backup_dir, f"therecipes_backup_{ts}.db")

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(backup_path)
    src.backup(dst)
    dst.close()
    src.close()

    size = os.path.getsize(backup_path)
    print(f"✓  Backup written to : {backup_path}")
    print(f"   Size              : {size:,} bytes ({size / 1024:.1f} KB)")


def cmd_status(args):
    """
    Print a summary of the database: file size, upload dir, and row counts.
    """
    if not os.path.isfile(DB_PATH):
        print(f"✗  No database found at: {DB_PATH}")
        sys.exit(1)

    conn = get_conn()
    size = os.path.getsize(DB_PATH)

    print(f"Database   : {DB_PATH}")
    print(f"Size       : {size:,} bytes ({size / 1024:.1f} KB)")
    print(f"Upload dir : {UPLOAD_DIR}")

    # Count images on disk
    if os.path.isdir(UPLOAD_DIR):
        img_count = sum(
            1 for f in os.listdir(UPLOAD_DIR)
            if os.path.isfile(os.path.join(UPLOAD_DIR, f))
        )
        print(f"Images     : {img_count:,} files in upload dir")
    else:
        print(f"Images     : upload dir not found (run 'initdb' to create it)")

    print()

    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    except sqlite3.OperationalError:
        print("No tables found (run 'initdb' first).")
        conn.close()
        return

    if not tables:
        print("No tables found.")
        conn.close()
        return

    print(f"{'Table':<25} {'Rows':>8}")
    print("─" * 35)
    for t in tables:
        name  = t["name"]
        count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        print(f"{name:<25} {count:>8,}")

    # Recipe summary
    print()
    try:
        total      = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        with_image = conn.execute("SELECT COUNT(*) FROM recipes WHERE image_path IS NOT NULL").fetchone()[0]
        cats       = conn.execute(
            "SELECT COUNT(DISTINCT dish_category) FROM recipes "
            "WHERE dish_category IS NOT NULL AND dish_category != ''"
        ).fetchone()[0]
        submitters = conn.execute(
            "SELECT COUNT(DISTINCT recipe_submitter) FROM recipes "
            "WHERE recipe_submitter IS NOT NULL AND recipe_submitter != ''"
        ).fetchone()[0]

        print(f"Recipes total    : {total:,}")
        print(f"With image       : {with_image:,}")
        print(f"Categories used  : {cats:,}")
        print(f"Submitters       : {submitters:,}")
    except Exception:
        pass

    conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

COMMANDS = {
    "initdb": cmd_initdb,
    "backup": cmd_backup,
    "status": cmd_status,
}


def main():
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="TheRecipes database management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "Commands:",
            "  initdb    Create tables (safe on existing DB — never overwrites data)",
            "  backup    Copy DB to a timestamped backup in the same directory",
            "  status    Show DB path, size, upload dir, and row counts",
            "",
            "Environment:",
            "  DB_PATH      Override database path",
            "               Default: /data/database/therecipes.db",
            "  UPLOAD_DIR   Override image upload directory",
            "               Default: /data/uploads/images",
            "",
            "Examples:",
            "  python manage.py initdb",
            "  DB_PATH=/tmp/test.db python manage.py initdb",
            "  python manage.py status",
            "  python manage.py backup",
        ])
    )
    parser.add_argument("command", choices=COMMANDS.keys())
    args = parser.parse_args()
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
