"""
app.py — TheRecipes web application

Standalone recipe management app. No OCR, no pipeline, no admin tooling.
Database must be initialised first with: python manage.py initdb
"""

import hashlib
import mimetypes
import os
import sqlite3
from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, abort, g
)

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "/data/database/therecipes.db")

CATEGORIES = [
    "Appetizer", "Baking", "Beverage", "Bread",
    "Breakfast", "Brunch", "Cake", "Candy",
    "Casserole", "Condiment", "Cookie", "Dessert",
    "Dip", "Drink", "Entree", "Fish & Seafood",
    "Freezer Meal", "Jam & Preserve", "Main Course",
    "Pasta", "Pastry", "Pickle", "Pie",
    "Pork", "Poultry", "Salad", "Sauce",
    "Side Dish", "Slow Cooker", "Snack", "Soup",
    "Vegetarian", "Other",
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


def _parse_rating(value) -> int:
    """Clamp to -1 (unrated) or 0–10."""
    try:
        r = int(value)
        return max(-1, min(10, r))
    except (TypeError, ValueError):
        return -1


def _hash_file(path: str) -> str | None:
    """SHA-256 of a local file. Returns None if file doesn't exist."""
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


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
    sort     = request.args.get("sort", "newest")   # newest | rating | title

    conditions, params = [], []
    if q:
        conditions.append("(r.title LIKE ? OR r.ingredients LIKE ? OR r.original_author LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if category:
        conditions.append("r.dish_category = ?")
        params.append(category)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    order = {
        "rating": "r.rating DESC, r.created_at DESC",
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
        "SELECT * FROM recipes WHERE id = ?", (recipe_id,)
    ).fetchone()
    if not recipe:
        abort(404)
    return render_template("recipe_view.html", recipe=recipe)


# ── New recipe ────────────────────────────────────────────────────────────────

@app.route("/recipes/new", methods=["GET", "POST"])
def recipe_new():
    if request.method == "POST":
        db     = get_db()
        rating = _parse_rating(request.form.get("rating", "-1"))
        image_path = request.form.get("image_path", "").strip() or None

        # Compute hash if image_path is a local file
        image_hash = None
        if image_path and not image_path.startswith(("http://", "https://")):
            image_hash = _hash_file(image_path)

        cur = db.execute("""
            INSERT INTO recipes
                (title, original_author, recipe_submitter, ingredients, instructions,
                 notes, dish_category, rating, image_path, image_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            request.form.get("title", "").strip() or None,
            request.form.get("original_author", "").strip() or None,
            request.form.get("recipe_submitter", "").strip() or None,
            request.form.get("ingredients", "").strip() or None,
            request.form.get("instructions", "").strip() or None,
            request.form.get("notes", "").strip() or None,
            request.form.get("dish_category", "").strip() or None,
            rating,
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
        "SELECT * FROM recipes WHERE id = ?", (recipe_id,)
    ).fetchone()
    if not recipe:
        abort(404)

    if request.method == "POST":
        rating     = _parse_rating(request.form.get("rating", "-1"))
        image_path = request.form.get("image_path", "").strip() or None

        # Recompute hash only if image_path changed
        image_hash = recipe["image_hash"]
        if image_path != recipe["image_path"]:
            if image_path and not image_path.startswith(("http://", "https://")):
                image_hash = _hash_file(image_path)
            else:
                image_hash = None

        db.execute("""
            UPDATE recipes
            SET title=?, original_author=?, recipe_submitter=?,
                ingredients=?, instructions=?, notes=?,
                dish_category=?, rating=?, image_path=?, image_hash=?
            WHERE id=?
        """, (
            request.form.get("title", "").strip() or None,
            request.form.get("original_author", "").strip() or None,
            request.form.get("recipe_submitter", "").strip() or None,
            request.form.get("ingredients", "").strip() or None,
            request.form.get("instructions", "").strip() or None,
            request.form.get("notes", "").strip() or None,
            request.form.get("dish_category", "").strip() or None,
            rating,
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
    db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    db.commit()
    return redirect(url_for("recipe_list"))


# ── Serve recipe image ────────────────────────────────────────────────────────

@app.route("/recipe/<int:recipe_id>/image")
def recipe_image(recipe_id):
    """
    Serve the recipe's attached image from the local filesystem.
    Only used when image_path is a local path, not a URL.
    """
    db     = get_db()
    recipe = db.execute(
        "SELECT image_path FROM recipes WHERE id = ?", (recipe_id,)
    ).fetchone()
    if not recipe or not recipe["image_path"]:
        abort(404)
    path = recipe["image_path"]
    if path.startswith(("http://", "https://")):
        abort(400)   # caller should use the URL directly
    if not os.path.isfile(path):
        abort(404)
    mime, _ = mimetypes.guess_type(path)
    return send_file(path, mimetype=mime or "image/jpeg")


# ── Search redirect ───────────────────────────────────────────────────────────

@app.route("/search")
def search():
    return redirect(url_for("recipe_list", q=request.args.get("q", "")))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
