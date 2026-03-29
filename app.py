"""
app.py — TheRecipes web application

Standalone recipe management app. No OCR, no pipeline, no admin tooling.
Database must be initialised first with: python manage.py initdb
"""

import hashlib
import json
import mimetypes
import os
import sqlite3
import uuid

import requests as http_requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, abort, g, jsonify, flash
)
from werkzeug.utils import secure_filename
from website_recipe_extractor import get_recipe_json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

DB_PATH = os.environ.get("DB_PATH", "/data/database/therecipes.db")

# All recipe images are stored here — the ONLY directory app.py will read/write.
# Set UPLOAD_DIR in the environment to override (e.g. for local development).
UPLOAD_DIR = os.path.realpath(
    os.environ.get("UPLOAD_DIR", "/data/uploads/images")
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_BYTES    = 10 * 1024 * 1024  # 10 MB

CATEGORIES = [
    "Appetizer",
    "Beverage",
    "Breakfast & Brunch",
    "Dessert",
    "Candy",
    "Meal",
    "Side Dish",
    "Soup & Stew",
    "Salad",
    "Pasta",
    "Seafood",
    "Vegetarian",
    "Condiment & Sauce",
    "Snack",
    "Preserve",
    "Other",
]

# ── Database helpers ──────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _normalize_name(raw: str) -> str:
    """
    Convert a person-name field to consistent proper case.
    Each word is capitalised; common name particles (de, van, von …) stay
    lowercase unless they open the string.
    Apostrophe contractions are handled correctly: O'Brien → O'Brien.
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
    Uses os.path.realpath to defeat symlink and path-traversal attacks.
    """
    real = os.path.realpath(path)
    return real.startswith(UPLOAD_DIR + os.sep) or real == UPLOAD_DIR


def _hash_file(path: str) -> str | None:
    """
    SHA-256 of a local file.
    Returns None if the file doesn't exist or is outside UPLOAD_DIR.
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


def save_image_from_url(url: str) -> str | None:
    """
    Download an image from a remote URL into UPLOAD_DIR.
    Validates content type and enforces MAX_IMAGE_BYTES.
    Returns the saved local path on success, None on any failure.
    """
    if not url.startswith(("http://", "https://")):
        return None
    try:
        resp = http_requests.get(url, timeout=15, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        ext = _ext_from_content_type(content_type)
        if not ext:
            ext = os.path.splitext(url.split("?")[0])[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return None

        filename = f"{uuid.uuid4()}{ext}"
        dest     = os.path.join(UPLOAD_DIR, filename)

        size = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    os.remove(dest)
                    return None
                f.write(chunk)

        return dest
    except Exception:
        return None


def save_image_from_upload(file_storage) -> str | None:
    """
    Save a Werkzeug FileStorage upload into UPLOAD_DIR.
    Validates extension and enforces MAX_IMAGE_BYTES.
    Returns the saved local path on success, None on any failure.
    """
    if not file_storage or not file_storage.filename:
        return None

    original_name = secure_filename(file_storage.filename)
    ext = os.path.splitext(original_name)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None

    filename = f"{uuid.uuid4()}{ext}"
    dest     = os.path.join(UPLOAD_DIR, filename)
    file_storage.save(dest)

    if os.path.getsize(dest) > MAX_IMAGE_BYTES:
        os.remove(dest)
        return None

    return dest


def _resolve_image(existing_path: str | None = None) -> tuple[str | None, str | None]:
    """
    Determine the image path and hash for a recipe save.

    Priority:
      1. Uploaded file  — multipart field "image_file"
      2. URL field      — form field "image_url", downloaded and stored locally
      3. Keep existing  — no new image submitted

    Returns (image_path, image_hash).
    On failure a flash warning is set and existing values are preserved
    so the recipe save still completes.
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


# ── Redirect root to recipes ──────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("recipe_list"))


# ── Recipe list ───────────────────────────────────────────────────────────────

@app.route("/recipes")
def recipe_list():
    db       = get_db()
    q        = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort     = request.args.get("sort", "newest")

    conditions, params = ["r.is_deleted = 0"], []
    if q:
        conditions.append("(r.title LIKE ? OR r.ingredients LIKE ? OR r.original_author LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if category:
        conditions.append("r.dish_category = ?")
        params.append(category)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = {
        "title":  "r.title ASC",
        "newest": "r.created_at DESC",
    }.get(sort, "r.created_at DESC")

    rows = db.execute(
        f"SELECT * FROM recipes r {where} ORDER BY {order}",
        params
    ).fetchall()

    all_categories = [row[0] for row in db.execute(
        "SELECT DISTINCT dish_category FROM recipes "
        "WHERE dish_category IS NOT NULL AND dish_category != '' "
        "ORDER BY dish_category"
    ).fetchall()]

    return render_template(
        "recipes.html",
        rows=rows, q=q, sort=sort,
        category=category, all_categories=all_categories,
    )


# ── Recipe view ───────────────────────────────────────────────────────────────

@app.route("/recipe/<int:recipe_id>")
def recipe_view(recipe_id):
    db     = get_db()
    recipe = db.execute(
        "SELECT * FROM recipes WHERE id = ? AND is_deleted = 0", (recipe_id,)
    ).fetchone()
    if not recipe:
        abort(404)
    return render_template("recipe_view.html", recipe=recipe)


# ── New recipe ────────────────────────────────────────────────────────────────

@app.route("/recipes/new", methods=["GET", "POST"])
def recipe_new():
    if request.method == "POST":
        db = get_db()

        raw_author    = request.form.get("original_author",  "").strip() or None
        raw_submitter = request.form.get("recipe_submitter", "").strip() or None
        author    = _normalize_name(raw_author)    if raw_author    else None
        submitter = _normalize_name(raw_submitter) if raw_submitter else None

        image_path, image_hash = _resolve_image()

        cur = db.execute("""
            INSERT INTO recipes
                (title, original_author, recipe_submitter, description, serving_size,
                 ingredients, instructions, dish_category, image_path, image_hash, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            request.form.get("title",        "").strip() or None,
            author,
            submitter,
            request.form.get("description",  "").strip() or None,
            request.form.get("serving_size", "").strip() or None,
            request.form.get("ingredients",  "").strip() or None,
            request.form.get("instructions", "").strip() or None,
            request.form.get("dish_category","").strip() or None,
            image_path,
            image_hash,
        ))
        db.commit()
        return redirect(url_for("recipe_view", recipe_id=cur.lastrowid))

    return render_template("recipe_form.html", recipe=None, categories=CATEGORIES)


# ── Edit recipe ───────────────────────────────────────────────────────────────

@app.route("/recipe/<int:recipe_id>/edit", methods=["GET", "POST"])
def recipe_edit(recipe_id):
    db     = get_db()
    recipe = db.execute(
        "SELECT * FROM recipes WHERE id = ? AND is_deleted = 0", (recipe_id,)
    ).fetchone()
    if not recipe:
        abort(404)

    if request.method == "POST":
        raw_author    = request.form.get("original_author",  "").strip() or None
        raw_submitter = request.form.get("recipe_submitter", "").strip() or None
        author    = _normalize_name(raw_author)    if raw_author    else None
        submitter = _normalize_name(raw_submitter) if raw_submitter else None

        image_path, image_hash = _resolve_image(existing_path=recipe["image_path"])

        db.execute("""
            UPDATE recipes
            SET title=?, original_author=?, recipe_submitter=?,
                description=?, serving_size=?,
                ingredients=?, instructions=?,
                dish_category=?, image_path=?, image_hash=?
            WHERE id=?
        """, (
            request.form.get("title",        "").strip() or None,
            author,
            submitter,
            request.form.get("description",  "").strip() or None,
            request.form.get("serving_size", "").strip() or None,
            request.form.get("ingredients",  "").strip() or None,
            request.form.get("instructions", "").strip() or None,
            request.form.get("dish_category","").strip() or None,
            image_path,
            image_hash,
            recipe_id,
        ))
        db.commit()
        return redirect(url_for("recipe_view", recipe_id=recipe_id))

    return render_template("recipe_form.html", recipe=recipe, categories=CATEGORIES)


# ── Delete recipe ─────────────────────────────────────────────────────────────

@app.route("/recipe/<int:recipe_id>/delete", methods=["POST"])
def recipe_delete(recipe_id):
    db = get_db()
    db.execute("UPDATE recipes SET is_deleted = 1 WHERE id = ?", (recipe_id,))
    db.commit()
    return redirect(url_for("recipe_list"))


# ── Serve recipe image ────────────────────────────────────────────────────────

@app.route("/recipe/<int:recipe_id>/image")
def recipe_image(recipe_id):
    """
    Serve a recipe's image from UPLOAD_DIR.
    Refuses to serve anything outside that directory (path-traversal guard).
    """
    db     = get_db()
    recipe = db.execute(
        "SELECT image_path FROM recipes WHERE id = ?", (recipe_id,)
    ).fetchone()

    if not recipe or not recipe["image_path"]:
        abort(404)

    path = recipe["image_path"]

    if path.startswith(("http://", "https://")):
        abort(400)

    if not _is_safe_image_path(path):
        abort(403)

    real = os.path.realpath(path)
    if not os.path.isfile(real):
        abort(404)

    mime, _ = mimetypes.guess_type(real)
    return send_file(real, mimetype=mime or "image/jpeg")


# ── Scrape recipe from URL ────────────────────────────────────────────────────

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    data = request.get_json(force=True) or {}
    url  = data.get("url", "").strip()
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"}), 400
    try:
        result = get_recipe_json(url, quiet=True)
        return app.response_class(result, status=200, mimetype="application/json")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Scrape page images for the image picker ───────────────────────────────────

@app.route("/api/recipe-images", methods=["POST"])
def api_recipe_images():
    """
    Fetch a recipe page and return all candidate image URLs found in <img> tags.

    The client is responsible for:
      - loading each URL to check natural dimensions (filter < 200px either axis)
      - sorting non-extractor images by area descending
      - keeping the extractor image first
      - capping the displayed set at 15

    Checks src, data-src, data-lazy-src, and data-original attributes in that
    order, skipping inline data: URIs.
    """
    data = request.get_json(force=True) or {}
    url  = data.get("url", "").strip()

    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Invalid URL", "images": []}), 400

    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        resp = http_requests.get(
            url, timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TheRecipes/1.0)"},
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Attributes checked in priority order; data: URIs are always skipped
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
                    break  # use the first non-empty attribute found

        return jsonify({"images": images})

    except Exception as e:
        return jsonify({"error": str(e), "images": []}), 500


# ── Search redirect ───────────────────────────────────────────────────────────

@app.route("/search")
def search():
    return redirect(url_for("recipe_list", q=request.args.get("q", "")))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
