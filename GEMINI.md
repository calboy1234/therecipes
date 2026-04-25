# TheRecipes - Project Context & Workflow

## Project Overview
A standalone recipe management application built with Flask and SQLAlchemy. It uses a "Trusted User" model where approved users can contribute and edit, while guests can browse securely.

## Development & Deployment Environment
- **Platform:** Docker-first (GitHub Actions builds the image).
- **Storage:** SQLite (using WAL mode for concurrency).
- **Operating System:** Windows (PowerShell) for development; Linux/Unraid for production.
- **Secrets:** Managed via `.env` files or Docker environment variables.

## Core Features
- **SQLAlchemy ORM:** Database agnostic (SQLite currently).
- **Authentication:** Flask-Login with hashed passwords and manual admin approval.
- **Privacy:** Sensitive authorship data and editing controls are hidden from unauthenticated guests.
- **Discord Integration:** Webhook notifications for new registrations.
- **Scraper:** Integrated `recipe-scrapers` for importing recipes from URLs.
- **Image Handling:** Secure local storage with SHA-256 deduplication.

## Roadmap (Updated)
1. **Security Hardening:** (Completed) Implementation of password hashing and guest privacy.
2. **User Management:** (Completed) CLI tools for approving users.
3. **Database Integrity:** (In Progress) Refinement of backup strategies.
4. **Versioning:** (Future) Audit logs for recipe edits.

## Maintenance & Testing
- **Test Artifacts:** `therecipes.db` and the `uploads/` folder are automatically created during manual or automated testing as the application initializes its database and handles image uploads.
- **Cleanup Reminder:** Developers should periodically check for these files and delete them if they are no longer needed for active development or debugging, ensuring they don't accidentally get committed or clutter the workspace.

## PowerShell Command Reference
- **Help:** `python manage.py help`
- **Initialize DB:** `python manage.py initdb`
- **List Pending Users:** `python manage.py ls-pending`
- **Approve User:** `python manage.py approve-user <username>`
- **Backup DB:** `python manage.py backup`
- **Status Check:** `python manage.py status`
