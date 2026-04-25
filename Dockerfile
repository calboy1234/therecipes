# ── TheRecipes Docker Image ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manage.py .
COPY app.py .
COPY website_recipe_extractor.py .
COPY templates/ ./templates/
COPY static/ ./static/

# /data   → persistent data directory (database and images)
VOLUME ["/data"]

EXPOSE 5000

CMD ["sh", "-c", "pip install --upgrade recipe-scrapers && python manage.py initdb && gunicorn --bind 0.0.0.0:5000 app:app"]
