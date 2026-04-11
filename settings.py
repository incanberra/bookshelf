import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SCHEMA_PATH = BASE_DIR / "schema.sql"
OPEN_LIBRARY_BOOKS_API = os.environ.get(
    "OPEN_LIBRARY_BOOKS_API",
    "https://openlibrary.org/api/books",
)
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
APP_PASSWORD = os.environ.get("APP_PASSWORD")
SECRET_KEY = os.environ.get("SECRET_KEY")
SESSION_COOKIE_SECURE = os.environ.get(
    "SESSION_COOKIE_SECURE",
    "0" if FLASK_DEBUG else "1",
) == "1"


def resolve_database_path() -> Path:
    explicit_path = os.environ.get("DATABASE_PATH")
    if explicit_path:
        return Path(explicit_path).expanduser()

    railway_mount_path = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if railway_mount_path:
        return Path(railway_mount_path) / "library.db"

    return BASE_DIR / "instance" / "library.db"


DATABASE_PATH = resolve_database_path()
