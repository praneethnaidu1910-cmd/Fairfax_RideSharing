FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# DATABASE_URL (and ALLOWED_ORIGINS, if the frontend is served from a
# different origin) is passed in at deploy time by the hosting platform --
# never baked into the image. Migrations run on every container start, not
# just once by hand, so a deploy with new migrations applies them before
# serving traffic; `alembic upgrade head` is a no-op once already current.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
