# Home Library Manager

A mobile-friendly Flask app for cataloguing books in a home library with SQLite storage, ISBN scanning, automatic metadata lookup from Open Library, separate user accounts, author progress tracking, and backup import/export tools.

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

3. Copy the example environment file and set your local admin credentials and secret:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Edit `.env` and set:

   ```text
   DEFAULT_ADMIN_USERNAME=owner
   DEFAULT_ADMIN_PASSWORD=your-password
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

7. Open `http://127.0.0.1:5000` and sign in with your username and password.

## Features

- Scan books by barcode or manual ISBN entry.
- Keep separate libraries for multiple users on the same deployment.
- Search, filter, and sort your catalogue on the page.
- Edit book details, toggle the `Stamped` flag, and delete books.
- Prompt on duplicate scans so you can track additional copies instead of creating accidental duplicates.
- Track author progress for Mick Herron, C.J. Box, and Bernard Cornwell.
- Export the library to JSON or CSV and restore JSON backups.
- Create additional user accounts from the admin dashboard.
- Re-seed the stored author progress targets with:

  ```powershell
  python sync_author_targets.py
  ```

## Accounts and authentication

The app now supports separate user accounts. Each account gets its own books, author progress data, and backup imports/exports. All catalogue pages and API routes still require authentication, while `/healthz` remains public for hosting health checks.

Required environment variables:

- `DEFAULT_ADMIN_PASSWORD`: the password for the initial owner account.
- `SECRET_KEY`: a long random secret used to sign the session cookie.

Optional:

- `DEFAULT_ADMIN_USERNAME`: defaults to `owner`.
- `DEFAULT_ADMIN_DISPLAY_NAME`: defaults to a title-cased version of the username.
- `APP_PASSWORD`: still works as a legacy fallback bootstrap password if `DEFAULT_ADMIN_PASSWORD` is not set.

Recommended:

- Use a long, unique admin password.
- Use a long random `SECRET_KEY`.
- Keep `SESSION_COOKIE_SECURE=1` in hosted environments so cookies are only sent over HTTPS.

If you are upgrading an existing single-password deployment, the app migrates the existing shared library into the owner account automatically on startup.

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

- `DEFAULT_ADMIN_USERNAME`: initial owner username. Defaults to `owner`.
- `DEFAULT_ADMIN_DISPLAY_NAME`: initial owner display name.
- `DEFAULT_ADMIN_PASSWORD`: initial owner password.
- `APP_PASSWORD`: legacy fallback for bootstrapping the first owner account.
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

- `DEFAULT_ADMIN_PASSWORD`
- `SECRET_KEY`

Deploy steps:

1. Push this repo to GitHub.
2. In Render, create a new Blueprint service from the repo.
3. Keep the attached disk enabled.
4. Set `DEFAULT_ADMIN_PASSWORD` and `SECRET_KEY` in the Render dashboard.
5. Use at least the `starter` plan, because persistent disks are required for SQLite persistence.

## Railway

This repo includes [railway.toml](/C:/Users/incan/OneDrive/Documents/CODEX/Library%20manager/railway.toml) with build and deploy commands.

Before your first deploy, add these environment variables in Railway:

- `DEFAULT_ADMIN_PASSWORD`
- `SECRET_KEY`

Deploy steps:

1. Push this repo to GitHub.
2. Create a new Railway project from the repo.
3. Add a Volume and mount it to your service, for example at `/data`.
4. Set `DEFAULT_ADMIN_PASSWORD` and `SECRET_KEY` in the Railway variables panel.
5. Redeploy.

When Railway provides `RAILWAY_VOLUME_MOUNT_PATH`, the app automatically stores the database at `<mount>/library.db`. If you prefer, you can set `DATABASE_PATH` manually instead.

## Important deployment note

This app uses SQLite, so keep it on a single running instance. Persistent disks and volumes make the file durable, but SQLite is still not the right choice for multi-instance horizontal scaling. If you later want autoscaling or multiple replicas, the next step is moving to Postgres.

## App behavior

- The `users` table stores account credentials and admin access.
- The `books` table stores `title`, `author`, `isbn`, `cover_image_url`, `stamped`, and `copy_count`, scoped per user.
- The `author_targets` table is stored per user so progress and restores stay separate.
- Scanned or manually entered ISBNs are posted to `/api/books/scan`.
- If the scanned ISBN already exists in that user's catalogue, the UI asks whether it is an additional copy and increments `copy_count` when confirmed.
- The backend looks up book metadata using the Open Library Books API and stores it in SQLite.
- The frontend uses `html5-qrcode` from `https://unpkg.com/html5-qrcode`.
- Camera access generally requires HTTPS or `localhost`.
