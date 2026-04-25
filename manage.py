#!/usr/bin/env python3
"""
manage.py — TheRecipes database management CLI

Usage:
    python manage.py initdb             Create tables if they don't exist
    python manage.py backup             Copy DB to a timestamped backup file
    python manage.py status             Show table info, row counts, etc.
    python manage.py approve-user <usr> Approve a registered user
    python manage.py revoke-user <usr>  Revoke a user's approval
    python manage.py batch-approve      Interactively approve multiple users

Environment:
    DB_PATH      Override the database path
    UPLOAD_DIR   Override the image upload directory
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from app import app, db, Recipe, User, UPLOAD_DIR, DB_PATH

# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_initdb(args):
    """
    Create all tables if they don't exist.
    """
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    print(f"✓  Upload directory ready  : {UPLOAD_DIR}")

    with app.app_context():
        db.create_all()
    
    print(f"✓  Database initialised at : {DB_PATH}")


def cmd_backup(args):
    """
    Copy the live database to a timestamped backup file in the same directory.
    Only works for SQLite.
    """
    if not os.path.isfile(DB_PATH):
        print(f"✗  No database found at: {DB_PATH}")
        sys.exit(1)

    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir  = os.path.dirname(DB_PATH)
    backup_path = os.path.join(backup_dir, f"therecipes_backup_{ts}.db")

    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        src.close()

        size = os.path.getsize(backup_path)
        print(f"✓  Backup written to : {backup_path}")
        print(f"   Size              : {size:,} bytes ({size / 1024:.1f} KB)")
    except Exception as e:
        print(f"✗  Backup failed: {e}")
        sys.exit(1)


def cmd_status(args):
    """
    Print a summary of the database: file size, upload dir, and row counts.
    """
    print(f"Database   : {DB_PATH}")
    if os.path.isfile(DB_PATH):
        size = os.path.getsize(DB_PATH)
        print(f"Size       : {size:,} bytes ({size / 1024:.1f} KB)")
    else:
        print(f"Size       : File not found")
        
    print(f"Upload dir : {UPLOAD_DIR}")

    # Count images on disk
    if os.path.isdir(UPLOAD_DIR):
        img_count = sum(
            1 for f in os.listdir(UPLOAD_DIR)
            if os.path.isfile(os.path.join(UPLOAD_DIR, f))
        )
        print(f"Images     : {img_count:,} files in upload dir")
    else:
        print(f"Images     : upload dir not found")

    print()

    with app.app_context():
        try:
            total      = Recipe.query.count()
            with_image = Recipe.query.filter(Recipe.image_path != None).count()
            cats       = db.session.query(Recipe.dish_category).distinct().filter(Recipe.dish_category != None, Recipe.dish_category != "").count()
            
            print(f"Recipes total    : {total:,}")
            print(f"With image       : {with_image:,}")
            print(f"Categories used  : {cats:,}")

            user_count = User.query.count()
            pending    = User.query.filter_by(is_approved=False).count()
            print(f"Users total      : {user_count:,} ({pending:,} pending approval)")
        except Exception as e:
            print(f"✗  Error fetching status: {e}")


def cmd_approve(args):
    """
    Approve a user by username.
    """
    with app.app_context():
        user = User.query.filter_by(username=args.username).first()
        if not user:
            print(f"✗  User not found: {args.username}")
            return
        
        user.is_approved = True
        db.session.commit()
        print(f"✓  User '{args.username}' has been approved.")


def cmd_revoke_user(args):
    """
    Revoke a user's approval.
    """
    with app.app_context():
        user = User.query.filter_by(username=args.username).first()
        if not user:
            print(f"✗  User not found: {args.username}")
            return
        
        user.is_approved = False
        db.session.commit()
        print(f"✓  Access revoked for user '{args.username}'. They are no longer approved.")


def cmd_lspending(args):
    """
    List all users pending approval.
    """
    with app.app_context():
        pending = User.query.filter_by(is_approved=False).order_by(User.created_at.asc()).all()
        if not pending:
            print("No users pending approval.")
            return

        print(f"{'Username':<20} {'Created At':<20} {'Wait Time'}")
        print("─" * 60)
        now = datetime.utcnow()
        for u in pending:
            wait = now - u.created_at
            days = wait.days
            hours = wait.seconds // 3600
            wait_str = f"{days}d {hours}h" if days > 0 else f"{hours}h {wait.seconds % 3600 // 60}m"
            print(f"{u.username:<20} {u.created_at.strftime('%Y-%m-%d %H:%M'):<20} {wait_str}")


def cmd_batch_approve(args):
    """
    Interactively approve users pending approval.
    """
    with app.app_context():
        pending = User.query.filter_by(is_approved=False).order_by(User.created_at.asc()).all()
        if not pending:
            print("No users pending approval.")
            return

        total = len(pending)
        print(f"There are {total} user(s) awaiting approval.\n")
        
        approved_count = 0
        now = datetime.utcnow()

        for i, user in enumerate(pending, 1):
            wait = now - user.created_at
            if wait.days > 0:
                time_str = f"{wait.days} day(s)"
            elif wait.seconds >= 3600:
                time_str = f"{wait.seconds // 3600} hour(s)"
            else:
                time_str = f"{wait.seconds // 60} minute(s)"

            prompt = f"Approve '{user.username}' (registered {time_str} ago)? [y/N] ({i}/{total}): "
            choice = input(prompt).lower().strip()

            if choice == 'y':
                user.is_approved = True
                db.session.commit()
                print(f"✓  User '{user.username}' approved.")
                approved_count += 1
            else:
                print(f"   Skipped '{user.username}'.")

        print(f"\nBatch complete. {approved_count} users approved.")


def cmd_help(args, parser):
    """
    Show the help message.
    """
    parser.print_help()


# ── CLI ───────────────────────────────────────────────────────────────────────

COMMANDS = {
    "initdb": cmd_initdb,
    "backup": cmd_backup,
    "status": cmd_status,
    "approve-user": cmd_approve,
    "revoke-user": cmd_revoke_user,
    "batch-approve": cmd_batch_approve,
    "ls-pending": cmd_lspending,
    "help": cmd_help,
}


def main():
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="TheRecipes database management CLI",
        add_help=False
    )
    
    # We add -h/--help manually so we can handle it or use the 'help' command
    parser.add_argument("-h", "--help", action="store_true", help="Show this help message")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("initdb", help="Create tables")
    subparsers.add_parser("backup", help="Backup SQLite DB")
    subparsers.add_parser("status", help="Show DB status")
    subparsers.add_parser("ls-pending", help="List users pending approval")
    subparsers.add_parser("batch-approve", help="Interactively approve users")
    subparsers.add_parser("help", help="Show this help message")

    approve_parser = subparsers.add_parser("approve-user", help="Approve a user")
    approve_parser.add_argument("username", help="Username to approve")

    revoke_parser = subparsers.add_parser("revoke-user", help="Revoke user approval")
    revoke_parser.add_argument("username", help="Username to revoke")

    # Manual check for invalid commands to provide the custom message requested
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd not in COMMANDS and cmd not in ["-h", "--help"]:
            print(f"'{cmd}' is not a valid command. For a list of commands and their description type 'python manage.py help'")
            sys.exit(1)

    args = parser.parse_args()

    if args.help or args.command == "help" or args.command is None:
        cmd_help(args, parser)
    else:
        COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
