#!/usr/bin/env python3
"""
manage.py — TheRecipes database management CLI

This script is the ONLY way to create or modify the database schema.
The Flask app has no database management code — it only reads and writes recipes.

Usage:
    python manage.py initdb     Create tables if they don't exist (safe on existing DB)
    python manage.py migrate    Apply schema changes to an existing database
    python manage.py backup     Copy DB to a timestamped backup file
    python manage.py status     Show table info, row counts, schema version

Environment:
    DB_PATH     Override the database path (default: /data/database/therecipes.db)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "/data/database/therecipes.db")

# Increment this whenever a migration is added below.
SCHEMA_VERSION = 1


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
    """
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS recipes (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        title             TEXT,
        original_author   TEXT,
        recipe_submitter  TEXT,
        ingredients       TEXT,
        instructions      TEXT,
        notes             TEXT,
        dish_category     TEXT,
        rating            INTEGER DEFAULT -1,
        image_path        TEXT,
        image_hash        TEXT,
        created_at        TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER PRIMARY KEY,
        applied_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Record initial version
    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
        (SCHEMA_VERSION,)
    )

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipes_category  ON recipes(dish_category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipes_rating    ON recipes(rating)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipes_submitter ON recipes(recipe_submitter)")

    conn.commit()
    conn.close()

    print(f"✓  Database initialised at: {DB_PATH}")
    print(f"   Schema version: {SCHEMA_VERSION}")


def cmd_migrate(args):
    """
    Apply any schema migrations needed to bring an existing database up to date.
    Add new migrations as additional `if current_version < N` blocks below.
    """
    conn = get_conn()
    cur  = conn.cursor()

    # Determine current version
    try:
        row     = cur.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] if row[0] is not None else 0
    except sqlite3.OperationalError:
        current = 0

    print(f"Current schema version : {current}")
    print(f"Target schema version  : {SCHEMA_VERSION}")

    if current >= SCHEMA_VERSION:
        print("✓  Already up to date — nothing to do.")
        conn.close()
        return

    # ── Future migrations go here ─────────────────────────────────────────────
    # Example pattern:
    #
    # if current < 2:
    #     cur.execute("ALTER TABLE recipes ADD COLUMN servings TEXT")
    #     cur.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (2)")
    #     print("  Applied migration 2: added 'servings' column")
    #
    # ─────────────────────────────────────────────────────────────────────────

    conn.commit()
    conn.close()
    print("✓  Migrations complete.")


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
    Print a summary of the database: file size, schema version, and row counts.
    """
    if not os.path.isfile(DB_PATH):
        print(f"✗  No database found at: {DB_PATH}")
        sys.exit(1)

    conn = get_conn()
    size = os.path.getsize(DB_PATH)

    print(f"Database  : {DB_PATH}")
    print(f"Size      : {size:,} bytes ({size / 1024:.1f} KB)")
    print()

    # Schema version
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        print(f"Schema version : {row[0] if row[0] is not None else 'unknown'}")
    except sqlite3.OperationalError:
        print("Schema version : unknown  (run 'initdb' first)")
    print()

    # Table row counts
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

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
        total   = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        rated   = conn.execute("SELECT COUNT(*) FROM recipes WHERE rating >= 0").fetchone()[0]
        cats    = conn.execute(
            "SELECT COUNT(DISTINCT dish_category) FROM recipes "
            "WHERE dish_category IS NOT NULL AND dish_category != ''"
        ).fetchone()[0]
        submitters = conn.execute(
            "SELECT COUNT(DISTINCT recipe_submitter) FROM recipes "
            "WHERE recipe_submitter IS NOT NULL AND recipe_submitter != ''"
        ).fetchone()[0]

        print(f"Recipes total    : {total:,}")
        print(f"Rated            : {rated:,}  ({rated/total*100:.0f}%)" if total else "Rated            : 0")
        print(f"Categories used  : {cats:,}")
        print(f"Submitters       : {submitters:,}")
    except Exception:
        pass

    conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

COMMANDS = {
    "initdb":  cmd_initdb,
    "migrate": cmd_migrate,
    "backup":  cmd_backup,
    "status":  cmd_status,
}


def main():
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="TheRecipes database management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "Commands:",
            "  initdb    Create tables (safe on existing DB — never overwrites data)",
            "  migrate   Apply schema changes to an existing database",
            "  backup    Copy DB to a timestamped backup in the same directory",
            "  status    Show DB path, size, schema version, and row counts",
            "",
            "Environment:",
            "  DB_PATH   Override database path",
            "            Default: /data/database/therecipes.db",
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
