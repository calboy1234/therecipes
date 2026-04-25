"""
app.py — TheRecipes web application

Standalone recipe management app. No OCR, no pipeline, no admin tooling.
Database must be initialised first with: python manage.py initdb
"""

import hashlib
import json
import mimetypes
import os
import uuid
import time
import random
import threading
import socket
import ipaddress
import sys
from datetime import datetime

import requests as http_requests

from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, abort, g, jsonify, flash
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import or_, event, Engine
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from website_recipe_extractor import get_recipe
from urllib.parse import urlparse

# ── Security Configuration ────────────────────────────────────────────────────

# Enforce SECRET_KEY from environment
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    print("CRITICAL ERROR: SECRET_KEY environment variable is missing.")
    print("The application cannot start without it for security reasons.")
    print("Please set SECRET_KEY in your environment or .env file.")
    sys.exit(1)

# Enable WAL mode for SQLite
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "True").lower() == "true" # Recommended for HTTPS
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

csrf = CSRFProtect(app)

# ── Database Configuration ────────────────────────────────────────────────────

# Default to /data for Docker persistence, fallback to current dir for dev
DB_PATH = os.environ.get("DB_PATH", os.path.join("/data", "therecipes.db"))

# Ensure DB directory exists
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

# Ensure DB_PATH is an absolute path
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.abspath(DB_PATH)

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# ── Models ────────────────────────────────────────────────────────────────────

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_approved   = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Recipe(db.Model):
    __tablename__ = "recipes"

    id               = db.Column(db.Integer, primary_key=True)
    title            = db.Column(db.String(255))
    original_author  = db.Column(db.String(255))
    recipe_submitter = db.Column(db.String(255))
    description      = db.Column(db.Text)
    serving_size     = db.Column(db.String(100))
    ingredients      = db.Column(db.Text)
    instructions     = db.Column(db.Text)
    dish_category    = db.Column(db.String(100), index=True)
    image_path       = db.Column(db.Text)
    image_hash       = db.Column(db.String(64))
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted       = db.Column(db.Integer, nullable=False, default=0, index=True)

    def __repr__(self):
        return f"<Recipe {self.title}>"


# ── Configuration & Helpers ───────────────────────────────────────────────────

# All recipe images are stored here — the ONLY directory app.py will read/write.
UPLOAD_DIR = os.path.realpath(
    os.environ.get("UPLOAD_DIR", os.path.join(os.getcwd(), "uploads", "images"))
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_BYTES    = 15 * 1024 * 1024  # 15 MB

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]

CATEGORIES = [
    c.strip() for c in os.environ.get(
        "RECIPE_CATEGORIES",
        "Meal,Dessert,Side,Breakfast,Appetizer,Beverage,Snack,Condiment,Preserves,Other"
    ).split(",") if c.strip()
]

# ── SSRF Protection Helper ────────────────────────────────────────────────────

def is_safe_url(url: str) -> bool:
    """
    Check if a URL is safe for server-side fetching.
    Prevents access to private/local network ranges.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        
        hostname = parsed.hostname
        if not hostname:
            return False

        # Resolve hostname to IP
        ip_addr = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_addr)

        # Block private, link-local, and loopback addresses
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False

        # Block non-standard ports (optional but recommended)
        if parsed.port and parsed.port not in (80, 443):
            return False

        return True
    except Exception:
        return False


def _normalize_name(raw: str) -> str:
    """
    Convert a person-name field to consistent proper case.
    """
    if not raw:
        return raw
    particles = {"de", "di", "du", "da", "del", "della", "von", "van",
                 "der", "den", "le", "la", "los", "las", "af", "av"}
    words = raw.strip().split()
    result = []
    for i, word in enumerate(words):
        if i > 0 and word.lower() in particles:
            result.append(word.lower())
        else:
            result.append("'".join(p.capitalize() for p in word.split("'")))
    return " ".join(result)


# ── Image helpers ─────────────────────────────────────────────────────────────

def _is_safe_image_path(path: str) -> bool:
    """
    Return True only if the resolved real path lives inside UPLOAD_DIR.
    """
    real = os.path.realpath(path)
    return real.startswith(UPLOAD_DIR + os.sep) or real == UPLOAD_DIR


def _hash_file(path: str) -> str | None:
    """
    SHA-256 of a local file.
    """
    if not path or not _is_safe_image_path(path):
        return None
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _ext_from_content_type(content_type: str) -> str | None:
    """Map a Content-Type header to a safe file extension."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png":  ".png",
        "image/gif":  ".gif",
        "image/webp": ".webp",
    }
    for mime, ext in mapping.items():
        if mime in content_type:
            return ext
    return None


def _delete_image_if_unused(path: str | None):
    """
    Delete a file from UPLOAD_DIR if it is no longer referenced by ANY recipe.
    """
    if not path or path.startswith(("http://", "https://")):
        return
    
    # Check if any other recipe uses this exact same path
    count = Recipe.query.filter_by(image_path=path).count()
    if count == 0:
        real_path = os.path.realpath(path)
        if _is_safe_image_path(real_path) and os.path.isfile(real_path):
            try:
                os.remove(real_path)
                print(f"[IMAGE CLEANUP] Deleted unused image: {path}")
            except Exception as e:
                print(f"[IMAGE CLEANUP] Error deleting {path}: {e}")


def save_image_from_url(url: str, max_retries: int = 3) -> str | None:
    """
    Download an image into UPLOAD_DIR using its SHA-256 hash as the filename.
    Returns the local path on success, None on failure.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None

    if not is_safe_url(url):
        print(f"[SECURITY] Blocked unsafe URL: {url}")
        return None

    for attempt in range(max_retries):
        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"https://{urlparse(url).netloc}/"
            }

            resp = http_requests.get(url, headers=headers, timeout=15, stream=True)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            ext = _ext_from_content_type(content_type)
            if not ext:
                ext = os.path.splitext(url.split("?")[0])[-1].lower()
            
            if ext not in ALLOWED_EXTENSIONS:
                return None

            # Stream to a temporary file first to calculate hash
            temp_filename = f"temp_{uuid.uuid4()}{ext}"
            temp_path     = os.path.join(UPLOAD_DIR, temp_filename)
            
            h = hashlib.sha256()
            size = 0
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        f.close()
                        os.remove(temp_path)
                        return None
                    f.write(chunk)
                    h.update(chunk)

            image_hash = h.hexdigest()
            final_filename = f"{image_hash}{ext}"
            final_path     = os.path.join(UPLOAD_DIR, final_filename)

            if os.path.exists(final_path):
                os.remove(temp_path)
                return final_path
            
            os.rename(temp_path, final_path)
            return final_path

        except Exception as e:
            print(f"[IMAGE LOG] Attempt {attempt + 1}/{max_retries} failed for {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 2) + random.random())
            else:
                return None


def save_image_from_upload(file_storage) -> str | None:
    """
    Save a Werkzeug FileStorage upload into UPLOAD_DIR using its hash.
    """
    if not file_storage or not file_storage.filename:
        return None

    original_name = secure_filename(file_storage.filename)
    ext = os.path.splitext(original_name)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None

    temp_filename = f"temp_{uuid.uuid4()}{ext}"
    temp_path     = os.path.join(UPLOAD_DIR, temp_filename)
    file_storage.save(temp_path)

    if os.path.getsize(temp_path) > MAX_IMAGE_BYTES:
        os.remove(temp_path)
        return None

    image_hash = _hash_file(temp_path)
    if not image_hash:
        os.remove(temp_path)
        return None

    final_filename = f"{image_hash}{ext}"
    final_path     = os.path.join(UPLOAD_DIR, final_filename)

    if os.path.exists(final_path):
        os.remove(temp_path)
        return final_path

    os.rename(temp_path, final_path)
    return final_path


def _resolve_image(existing_path: str | None = None) -> tuple[str | None, str | None]:
    """
    Determine the image path and hash for a recipe save.
    """
    uploaded  = request.files.get("image_file")
    url_input = request.form.get("image_url", "").strip()

    if uploaded and uploaded.filename:
        path = save_image_from_upload(uploaded)
        if path:
            return path, _hash_file(path)
        flash("Image upload failed — unsupported format or file too large (max 10 MB).", "warning")

    elif url_input:
        path = save_image_from_url(url_input)
        if path:
            return path, _hash_file(path)
        flash("Could not download the image from that URL.", "warning")

    return existing_path, _hash_file(existing_path) if existing_path else None


# ── Auth Configuration & Routes ───────────────────────────────────────────────

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _send_discord_notification(username):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    try:
        payload = {
            "embeds": [{
                "title": "🆕 New User Registration",
                "description": f"User **{username}** has registered and is awaiting approval.",
                "color": 12590123,
                "fields": [
                    {"name": "Action Required", "value": f"Run `python manage.py approve-user {username}` to approve."}
                ],
                "timestamp": datetime.utcnow().isoformat()
            }]
        }
        http_requests.post(webhook_url, json=payload, timeout=5)
    except Exception as e:
        print(f"[ERROR] Failed to send Discord notification: {e}")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("recipe_list"))
    
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        
        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for("register"))
        
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        threading.Thread(target=_send_discord_notification, args=(username,), daemon=True).start()
        
        flash("Registration successful! Please wait for an administrator to approve your account.", "info")
        return redirect(url_for("login"))
    
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("recipe_list"))
    
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if not user.is_approved:
                flash("Your account is pending approval.", "warning")
                return redirect(url_for("login"))
            
            login_user(user)
            return redirect(url_for("recipe_list"))
        else:
            flash("Invalid username or password.", "danger")
    
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("recipe_list"))


# ── Recipe Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("recipe_list"))


@app.route("/recipes")
def recipe_list():
    q        = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort     = request.args.get("sort", "newest")

    query = Recipe.query.filter_by(is_deleted=0)

    if q:
        query = query.filter(or_(
            Recipe.title.ilike(f"%{q}%"),
            Recipe.ingredients.ilike(f"%{q}%"),
            Recipe.original_author.ilike(f"%{q}%")
        ))
    
    if category:
        query = query.filter_by(dish_category=category)

    if sort == "title":
        query = query.order_by(Recipe.title.asc())
    else:
        query = query.order_by(Recipe.created_at.desc())

    rows = query.all()

    all_categories = db.session.query(Recipe.dish_category).distinct().\
        filter(Recipe.dish_category != None, Recipe.dish_category != "").\
        order_by(Recipe.dish_category).all()
    all_categories = [c[0] for c in all_categories]

    return render_template(
        "recipes.html",
        rows=rows, q=q, sort=sort,
        category=category, all_categories=all_categories,
        is_authenticated=current_user.is_authenticated
    )


@app.route("/recipe/<int:recipe_id>")
def recipe_view(recipe_id):
    recipe = Recipe.query.filter_by(id=recipe_id, is_deleted=0).first()
    if not recipe:
        abort(404)
    return render_template("recipe_view.html", recipe=recipe, is_authenticated=current_user.is_authenticated)


@app.route("/recipes/new", methods=["GET", "POST"])
@login_required
def recipe_new():
    if request.method == "POST":
        raw_author    = request.form.get("original_author",  "").strip() or None
        raw_submitter = request.form.get("recipe_submitter", "").strip() or None
        author    = _normalize_name(raw_author)    if raw_author    else None
        submitter = _normalize_name(raw_submitter) if raw_submitter else None

        image_path, image_hash = _resolve_image()

        recipe = Recipe(
            title            = request.form.get("title",        "").strip() or None,
            original_author  = author,
            recipe_submitter = submitter,
            description      = request.form.get("description",  "").strip() or None,
            serving_size     = request.form.get("serving_size", "").strip() or None,
            ingredients      = request.form.get("ingredients",  "").strip() or None,
            instructions     = request.form.get("instructions", "").strip() or None,
            dish_category    = request.form.get("dish_category","").strip() or None,
            image_path       = image_path,
            image_hash       = image_hash,
            is_deleted       = 0
        )
        db.session.add(recipe)
        db.session.commit()
        return redirect(url_for("recipe_view", recipe_id=recipe.id))

    return render_template("recipe_form.html", recipe=None, categories=CATEGORIES, default_submitter=current_user.username)


@app.route("/recipe/<int:recipe_id>/edit", methods=["GET", "POST"])
@login_required
def recipe_edit(recipe_id):
    recipe = Recipe.query.filter_by(id=recipe_id, is_deleted=0).first()
    if not recipe:
        abort(404)

    if request.method == "POST":
        old_path = recipe.image_path
        
        raw_author    = request.form.get("original_author",  "").strip() or None
        raw_submitter = request.form.get("recipe_submitter", "").strip() or None
        author    = _normalize_name(raw_author)    if raw_author    else None
        submitter = _normalize_name(raw_submitter) if raw_submitter else None

        image_path, image_hash = _resolve_image(existing_path=recipe.image_path)

        recipe.title            = request.form.get("title",        "").strip() or None
        recipe.original_author  = author
        recipe.recipe_submitter = submitter
        recipe.description      = request.form.get("description",  "").strip() or None
        recipe.serving_size     = request.form.get("serving_size", "").strip() or None
        recipe.ingredients      = request.form.get("ingredients",  "").strip() or None
        recipe.instructions     = request.form.get("instructions", "").strip() or None
        recipe.dish_category    = request.form.get("dish_category","").strip() or None
        recipe.image_path       = image_path
        recipe.image_hash       = image_hash
        
        db.session.commit()

        if image_path != old_path:
            _delete_image_if_unused(old_path)

        return redirect(url_for("recipe_view", recipe_id=recipe_id))

    return render_template("recipe_form.html", recipe=recipe, categories=CATEGORIES)


@app.route("/recipe/<int:recipe_id>/delete", methods=["POST"])
@login_required
def recipe_delete(recipe_id):
    recipe = Recipe.query.get(recipe_id)
    if recipe:
        recipe.is_deleted = 1
        db.session.commit()
    return redirect(url_for("recipe_list"))


@app.route("/recipe/<int:recipe_id>/image")
def recipe_image(recipe_id):
    recipe = Recipe.query.get(recipe_id)
    if not recipe or not recipe.image_path:
        abort(404)
    path = recipe.image_path
    if path.startswith(("http://", "https://")):
        abort(400)
    if not _is_safe_image_path(path):
        abort(403)
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        abort(404)
    mime, _ = mimetypes.guess_type(real)
    return send_file(real, mimetype=mime or "image/jpeg")


# ── API Routes ────────────────────────────────────────────────────────────────

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    data = request.get_json(force=True) or {}
    url  = data.get("url", "").strip()
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"}), 400
    if not is_safe_url(url):
        return jsonify({"status": "error", "message": "Unsafe URL blocked"}), 400
    try:
        result = get_recipe(url) 
        if result.get("status") == "error":
            return jsonify(result), 400
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/recipe-images", methods=["POST"])
def api_recipe_images():
    data = request.get_json(force=True) or {}
    url  = data.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Invalid URL", "images": []}), 400
    if not is_safe_url(url):
        return jsonify({"error": "Unsafe URL blocked", "images": []}), 400
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        resp = http_requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (compatible; TheRecipes/1.0)"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        SRC_ATTRS = ("src", "data-src", "data-lazy-src", "data-original")
        seen, images = set(), []
        for tag in soup.find_all("img"):
            for attr in SRC_ATTRS:
                raw = (tag.get(attr) or "").strip()
                if raw and not raw.startswith("data:"):
                    abs_src = urljoin(url, raw)
                    if abs_src.startswith(("http://", "https://")) and abs_src not in seen:
                        seen.add(abs_src)
                        images.append(abs_src)
                    break
        return jsonify({"images": images})
    except Exception as e:
        return jsonify({"error": str(e), "images": []}), 500


@app.route("/search")
def search():
    return redirect(url_for("recipe_list", q=request.args.get("q", "")))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
