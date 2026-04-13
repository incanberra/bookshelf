import json
import re
import sqlite3
from datetime import datetime, timezone

from auth_utils import hash_password
from library_defaults import AUTHOR_PROGRESS_DEFAULTS
from settings import (
    DATABASE_PATH,
    DEFAULT_ADMIN_DISPLAY_NAME,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    SCHEMA_PATH,
)


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")

USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    created_at TEXT NOT NULL,
    last_login_at TEXT
)
"""

BOOKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    isbn TEXT NOT NULL,
    cover_image_url TEXT,
    stamped INTEGER NOT NULL DEFAULT 0 CHECK (stamped IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, isbn)
)
"""

AUTHOR_TARGETS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS author_targets (
    user_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    author_key TEXT,
    total_books INTEGER NOT NULL CHECK (total_books >= 0),
    aliases_json TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, author_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
)
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: object | None) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_username(raw_username: object | None) -> str:
    return clean_text(raw_username).lower()


def create_connection(database_path=DATABASE_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def fetch_user_by_id(connection: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, username, display_name, password_hash, is_admin, created_at, last_login_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def fetch_user_by_username(connection: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, username, display_name, password_hash, is_admin, created_at, last_login_at
        FROM users
        WHERE username = ?
        """,
        (normalize_username(username),),
    ).fetchone()


def list_user_ids(connection: sqlite3.Connection) -> list[int]:
    return [
        int(row["id"])
        for row in connection.execute("SELECT id FROM users ORDER BY id ASC").fetchall()
    ]


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.match(normalized):
        raise ValueError(
            "Usernames must be 3-32 characters and use lowercase letters, numbers, dots, hyphens, or underscores."
        )
    return normalized


def validate_password(password: object | None) -> str:
    prepared_password = str(password or "")
    if len(prepared_password) < 8:
        raise ValueError("Passwords must be at least 8 characters long.")
    return prepared_password


def seed_author_targets(
    connection: sqlite3.Connection,
    *,
    user_id: int,
    overwrite: bool = False,
    targets: list[dict] | tuple[dict, ...] | None = None,
) -> int:
    seeded_count = 0
    active_targets = list(targets or AUTHOR_PROGRESS_DEFAULTS)

    for position, target in enumerate(active_targets, start=1):
        author_name = clean_text(target["author_name"])
        aliases = target.get("aliases") or [author_name]
        payload = (
            int(user_id),
            author_name,
            target.get("author_key"),
            int(target["total_books"]),
            json.dumps(aliases, ensure_ascii=False),
            int(target.get("sort_order", position)),
            target.get("source_url"),
            target.get("updated_at") or utc_now_iso(),
        )

        if overwrite:
            connection.execute(
                """
                INSERT INTO author_targets (
                    user_id, author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, author_name) DO UPDATE SET
                    author_key = excluded.author_key,
                    total_books = excluded.total_books,
                    aliases_json = excluded.aliases_json,
                    sort_order = excluded.sort_order,
                    source_url = excluded.source_url,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            seeded_count += 1
            continue

        connection.execute(
            """
            INSERT OR IGNORE INTO author_targets (
                user_id, author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        seeded_count += connection.execute("SELECT changes()").fetchone()[0]

    return seeded_count


def seed_author_targets_for_all_users(
    connection: sqlite3.Connection,
    *,
    overwrite: bool = False,
    targets: list[dict] | tuple[dict, ...] | None = None,
) -> int:
    return sum(
        seed_author_targets(
            connection,
            user_id=user_id,
            overwrite=overwrite,
            targets=targets,
        )
        for user_id in list_user_ids(connection)
    )


def create_user(
    connection: sqlite3.Connection,
    *,
    username: object | None,
    password: object | None,
    display_name: object | None = None,
    is_admin: bool = False,
    seed_defaults: bool = True,
) -> sqlite3.Row:
    normalized_username = validate_username(str(username or ""))
    prepared_password = validate_password(password)
    prepared_display_name = clean_text(display_name) or normalized_username.replace("-", " ").replace("_", " ").title()
    created_at = utc_now_iso()

    try:
        cursor = connection.execute(
            """
            INSERT INTO users (username, display_name, password_hash, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_username,
                prepared_display_name,
                hash_password(prepared_password),
                1 if is_admin else 0,
                created_at,
            ),
        )
    except sqlite3.IntegrityError as error:
        message = str(error).lower()
        if "users.username" in message or "unique constraint failed: users.username" in message:
            raise ValueError("That username is already in use.") from error
        raise

    created_user = fetch_user_by_id(connection, cursor.lastrowid)
    if created_user is None:
        raise RuntimeError("The new user account could not be loaded after creation.")

    if seed_defaults:
        seed_author_targets(connection, user_id=created_user["id"])

    return created_user


def update_user_last_login(connection: sqlite3.Connection, user_id: int) -> None:
    connection.execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?",
        (utc_now_iso(), user_id),
    )


def ensure_initial_admin_user(connection: sqlite3.Connection) -> sqlite3.Row:
    configured_username = normalize_username(DEFAULT_ADMIN_USERNAME) or "owner"
    configured_display_name = clean_text(DEFAULT_ADMIN_DISPLAY_NAME) or configured_username.title()

    existing_user = fetch_user_by_username(connection, configured_username)
    if existing_user is not None:
        if not existing_user["is_admin"]:
            connection.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (existing_user["id"],))
            existing_user = fetch_user_by_id(connection, existing_user["id"])
        return existing_user

    user_count = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    if user_count:
        return connection.execute(
            """
            SELECT id, username, display_name, password_hash, is_admin, created_at, last_login_at
            FROM users
            ORDER BY is_admin DESC, id ASC
            LIMIT 1
            """
        ).fetchone()

    if not DEFAULT_ADMIN_PASSWORD:
        raise RuntimeError(
            "DEFAULT_ADMIN_PASSWORD or APP_PASSWORD must be set before the first multi-user startup."
        )

    return create_user(
        connection,
        username=configured_username,
        display_name=configured_display_name,
        password=DEFAULT_ADMIN_PASSWORD,
        is_admin=True,
        seed_defaults=False,
    )


def migrate_books_table(connection: sqlite3.Connection, owner_user_id: int) -> bool:
    if not table_exists(connection, "books"):
        connection.execute(BOOKS_TABLE_SQL)
        return False

    columns = get_table_columns(connection, "books")
    if {"user_id", "created_at", "updated_at"}.issubset(columns):
        return False

    legacy_rows = connection.execute(
        """
        SELECT id, title, author, isbn, cover_image_url, stamped
        FROM books
        ORDER BY id ASC
        """
    ).fetchall()

    connection.execute("ALTER TABLE books RENAME TO books_legacy_pre_multi_user")
    connection.execute(BOOKS_TABLE_SQL)

    migrated_at = utc_now_iso()
    for row in legacy_rows:
        connection.execute(
            """
            INSERT INTO books (
                id, user_id, title, author, isbn, cover_image_url, stamped, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                owner_user_id,
                row["title"],
                row["author"],
                row["isbn"],
                row["cover_image_url"],
                row["stamped"],
                migrated_at,
                migrated_at,
            ),
        )

    connection.execute("DROP TABLE books_legacy_pre_multi_user")
    return True


def migrate_author_targets_table(connection: sqlite3.Connection, owner_user_id: int) -> bool:
    if not table_exists(connection, "author_targets"):
        connection.execute(AUTHOR_TARGETS_TABLE_SQL)
        return False

    columns = get_table_columns(connection, "author_targets")
    if "user_id" in columns:
        return False

    legacy_rows = connection.execute(
        """
        SELECT author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
        FROM author_targets
        ORDER BY sort_order ASC, author_name COLLATE NOCASE ASC
        """
    ).fetchall()

    connection.execute("ALTER TABLE author_targets RENAME TO author_targets_legacy_pre_multi_user")
    connection.execute(AUTHOR_TARGETS_TABLE_SQL)

    for row in legacy_rows:
        connection.execute(
            """
            INSERT INTO author_targets (
                user_id, author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_user_id,
                row["author_name"],
                row["author_key"],
                row["total_books"],
                row["aliases_json"],
                row["sort_order"],
                row["source_url"],
                row["updated_at"],
            ),
        )

    connection.execute("DROP TABLE author_targets_legacy_pre_multi_user")
    return True


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with create_connection(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(USERS_TABLE_SQL)
        initial_admin = ensure_initial_admin_user(connection)
        migrate_books_table(connection, initial_admin["id"])
        migrate_author_targets_table(connection, initial_admin["id"])
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        seed_author_targets_for_all_users(connection)
        connection.commit()


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialised at {DATABASE_PATH}")
