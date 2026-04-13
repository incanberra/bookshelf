# Home Library Manager

A mobile-friendly Flask app for cataloguing books in a home library with SQLite storage, ISBN scanning, automatic metadata lookup from Open Library, shared-password protection, author progress tracking, and backup import/export tools.

## Local development

1. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy the example environment file and set your local password and secret:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Edit `.env` and set:

   ```text
   APP_PASSWORD=your-password
   SECRET_KEY=your-long-random-secret
   ```

5. Initialise the database:

   ```powershell
   python init_db.py
   ```

6. Start the development server:

   ```powershell
   python app.py
   ```

7. Open `http://127.0.0.1:5000` and sign in with your password.

## Features

- Scan books by barcode or manual ISBN entry.
- Search, filter, and sort your catalogue on the page.
- Edit book details, toggle the `Stamped` flag, and delete books.
- Track author progress for Mick Herron, C.J. Box, and Bernard Cornwell.
- Export the library to JSON or CSV and restore JSON backups.
- Re-seed the stored author progress targets with:

  ```powershell
  python sync_author_targets.py
  ```

## Password protection

The app is now protected by a single shared password. All catalogue pages and API routes require authentication, while `/healthz` remains public for hosting health checks.

Required environment variables:

- `APP_PASSWORD`: the shared password used on the login page.
- `SECRET_KEY`: a long random secret used to sign the session cookie.

Recommended:

- Use a long, unique password.
- Use a long random `SECRET_KEY`.
- Keep `SESSION_COOKIE_SECURE=1` in hosted environments so cookies are only sent over HTTPS.

## Production entrypoint

The repo is set up for a production WSGI server with Gunicorn:

```bash
gunicorn wsgi:app
```

Gunicorn reads its settings from `gunicorn.conf.py`, including:

- `PORT`
- `WEB_CONCURRENCY`
- `GUNICORN_THREADS`
- `GUNICORN_TIMEOUT`

The default worker count is `1` because SQLite is safest with a single app instance.

## Environment variables

The app resolves runtime settings from environment variables, optionally loaded from a local `.env` file:

- `APP_PASSWORD`: required login password.
- `SECRET_KEY`: required session signing secret.
- `DATABASE_PATH`: explicit full path to the SQLite file.
- `RAILWAY_VOLUME_MOUNT_PATH`: if present and `DATABASE_PATH` is not set, the app uses `<mount>/library.db`.
- `FLASK_DEBUG`: set to `1` for local debug mode.
- `PORT`: server port for local or hosted environments.
- `HOST`: bind host for local runs. Defaults to `0.0.0.0`.
- `SESSION_COOKIE_SECURE`: set to `1` for HTTPS-only cookies.
- `OPEN_LIBRARY_BOOKS_API`: optional override for the metadata API endpoint.

Local fallback remains `instance/library.db`.

## Healthcheck

The app exposes a lightweight health endpoint for hosting providers:

```text
GET /healthz
```

## Render

This repo includes [render.yaml](/C:/Users/incan/OneDrive/Documents/CODEX/Library%20manager/render.yaml), which configures:

- A Python web service
- `gunicorn wsgi:app` as the start command
- `/healthz` as the healthcheck path
- A persistent disk mounted at `/var/data`
- `DATABASE_PATH=/var/data/library.db`

Before your first deploy, add these environment variables in Render:

- `APP_PASSWORD`
- `SECRET_KEY`

Deploy steps:

1. Push this repo to GitHub.
2. In Render, create a new Blueprint service from the repo.
3. Keep the attached disk enabled.
4. Set `APP_PASSWORD` and `SECRET_KEY` in the Render dashboard.
5. Use at least the `starter` plan, because persistent disks are required for SQLite persistence.

## Railway

This repo includes [railway.toml](/C:/Users/incan/OneDrive/Documents/CODEX/Library%20manager/railway.toml) with build and deploy commands.

Before your first deploy, add these environment variables in Railway:

- `APP_PASSWORD`
- `SECRET_KEY`

Deploy steps:

1. Push this repo to GitHub.
2. Create a new Railway project from the repo.
3. Add a Volume and mount it to your service, for example at `/data`.
4. Set `APP_PASSWORD` and `SECRET_KEY` in the Railway variables panel.
5. Redeploy.

When Railway provides `RAILWAY_VOLUME_MOUNT_PATH`, the app automatically stores the database at `<mount>/library.db`. If you prefer, you can set `DATABASE_PATH` manually instead.

## Important deployment note

This app uses SQLite, so keep it on a single running instance. Persistent disks and volumes make the file durable, but SQLite is still not the right choice for multi-instance horizontal scaling. If you later want autoscaling or multiple replicas, the next step is moving to Postgres.

## App behavior

- The `books` table stores `title`, `author`, `isbn`, `cover_image_url`, and `stamped`.
- Scanned or manually entered ISBNs are posted to `/api/books/scan`.
- The backend looks up book metadata using the Open Library Books API and stores it in SQLite.
- The frontend uses `html5-qrcode` from `https://unpkg.com/html5-qrcode`.
- Camera access generally requires HTTPS or `localhost`.
