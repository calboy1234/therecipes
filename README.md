# TheRecipes

A standalone, secure recipe management application built with Flask and SQLAlchemy.

## 🚀 Deployment (Docker / Unraid)

This application is designed to run as a Docker container.

### 1. Environment Variables
Configure these in your Docker setup (Unraid Template or Docker Run command) or `.env` file for local development:

| Variable | Description | Default / Recommended |
| :--- | :--- | :--- |
| `SECRET_KEY` | Secures user sessions and CSRF tokens. **Required.** | A long random string. |
| `SESSION_COOKIE_SECURE` | Set to `False` for local testing on `http`. Set to `True` for production `https`. | `True` |
| `DISCORD_WEBHOOK_URL` | Notify Discord of new signups. | `https://discord.com/api/webhooks/...` |
| `DB_PATH` | Internal path to the SQLite database file. | `/data/therecipes.db` |
| `UPLOAD_DIR` | Internal path where recipe images are stored. | `/data/images` |
| `DATABASE_URL` | Override the DB connection (e.g. for external Postgres). | `sqlite:////data/therecipes.db` |
| `RECIPE_CATEGORIES` | Comma-separated list of categories for the recipe form. | `Meal,Dessert,Side,Breakfast,...` |

### 2. Volume Mounts
To ensure your data persists when the container updates, mount a host directory to `/data`:

- **Host Path:** `/mnt/user/appdata/therecipes` (or similar)
- **Container Path:** `/data`

### 3. Docker Run Example
```bash
docker run -d \
  --name="TheRecipes" \
  -p 5000:5000 \
  -v /mnt/user/appdata/therecipes:/data \
  -e SECRET_KEY="your-random-secret" \
  -e DISCORD_WEBHOOK_URL="your-webhook-url" \
  ghcr.io/your-username/therecipes:latest
```

---

## 🔐 User Authentication & Approval

TheRecipes uses a **"Trusted User"** model:
1.  **Register:** Anyone can visit the `/register` page.
2.  **Pending:** New accounts are disabled until approved by the administrator.
3.  **Approve:** Use the CLI (see below) to approve the user.
4.  **Full Access:** Approved users can create and edit **all** recipes. Guests can only browse and search.

---

## 🛠 Management Commands (CLI)

Since the app runs in Docker, you execute these commands via `docker exec`. Replace `therecipes` with your container name.

### Initialize/Fix Database
Use this if you are starting fresh or moving to a new version.
```bash
docker exec -it therecipes python manage.py initdb
```

### List Users Awaiting Approval
```bash
docker exec -it therecipes python manage.py ls-pending
```

### Approve a User
```bash
docker exec -it therecipes python manage.py approve-user <username>
```

### Create a Database Backup
Creates a timestamped `.db` file in your `/data` folder.
```bash
docker exec -it therecipes python manage.py backup
```

### Check System Status
```bash
docker exec -it therecipes python manage.py status
```

---

## 🛡 Security Deep Dive

- **Password Hashing:** Passwords are never stored in plain text. We use `scrypt` hashing via `werkzeug.security`.
- **Session Security:** Cookies are signed and marked `HttpOnly`.
- **Path Traversal Guard:** The image server strictly validates that requested files live inside the `UPLOAD_DIR` using realpath resolution.
- **Privacy Mode:** "Original Author" and "Added By" fields are stripped from the HTML responses for unauthenticated guests.
- **SQLite WAL Mode:** Enabled by default to prevent "Database Locked" errors during concurrent access.
