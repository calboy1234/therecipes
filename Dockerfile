# ── TheRecipes Docker Image ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manage.py  .
COPY app.py     .
COPY templates/ ./templates/
COPY static/    ./static/

# /data   → persistent data directory (database lives at /data/database/)
# /images → optional: local recipe image files (if using filesystem image_path)
VOLUME ["/data", "/images"]

EXPOSE 5000

# Database must be initialised before first run:
#   docker exec therecipes python manage.py initdb
CMD ["python", "app.py"]
