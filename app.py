import csv
from datetime import datetime, timezone
import io
import json
import os
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import Flask, Response, g, redirect, render_template, request, session, url_for

from auth_utils import verify_password
from init_db import (
    clean_text,
    create_connection,
    create_user,
    fetch_user_by_id,
    fetch_user_by_username,
    initialize_database,
    normalize_username,
    seed_author_targets,
    update_user_last_login,
)
from settings import (
    DATABASE_PATH,
    DEFAULT_ADMIN_USERNAME,
    FLASK_DEBUG,
    HOST,
    OPEN_LIBRARY_BOOKS_API,
    PORT,
    SECRET_KEY,
    SESSION_COOKIE_SECURE,
)


if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set before starting the app.")


app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
)

initialize_database()

EXEMPT_ENDPOINTS = {"healthcheck", "login", "logout", "static"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_safe_redirect_target(target: str | None) -> bool:
    return bool(target) and target.startswith("/") and not target.startswith("//")


def get_db_connection() -> sqlite3.Connection:
    return create_connection(DATABASE_PATH)


def authentication_required_response():
    if request.path.startswith("/api/"):
        return {"error": "Authentication required."}, 401

    next_target = request.full_path.rstrip("?") if request.query_string else request.path
    return redirect(url_for("login", next=next_target))


@app.before_request
def require_authentication():
    g.current_user = None

    if request.endpoint is None or request.endpoint in EXEMPT_ENDPOINTS:
        return None

    user_id = session.get("user_id")
    if not user_id:
        return authentication_required_response()

    with get_db_connection() as connection:
        user = fetch_user_by_id(connection, int(user_id))

    if user is None:
        session.clear()
        return authentication_required_response()

    g.current_user = user
    return None


def admin_required_response():
    return {"error": "Admin access is required for that action."}, 403


def serialize_current_user(user: sqlite3.Row | dict | None) -> dict | None:
    if user is None:
        return None

    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "is_admin": bool(user["is_admin"]),
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }


def serialize_user_summary(user: sqlite3.Row | dict) -> dict:
    user_keys = user.keys() if hasattr(user, "keys") else user
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "is_admin": bool(user["is_admin"]),
        "book_count": int(user["book_count"]) if "book_count" in user_keys else 0,
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }


def normalize_isbn(raw_isbn: object | None) -> str:
    normalized = "".join(
        character
        for character in clean_text(raw_isbn).upper()
        if character.isdigit() or character == "X"
    )

    if len(normalized) not in {10, 13}:
        raise ValueError("ISBN scans must contain 10 or 13 characters.")

    return normalized


def normalize_lookup_text(value: object | None) -> str:
    collapsed = []
    last_was_space = True

    for character in clean_text(value).lower():
        if character.isalnum():
            collapsed.append(character)
            last_was_space = False
        elif not last_was_space:
            collapsed.append(" ")
            last_was_space = True

    return "".join(collapsed).strip()


def coerce_stamped(value: object | None, fallback: bool = False) -> int:
    if value is None:
        return 1 if fallback else 0

    if isinstance(value, bool):
        return 1 if value else 0

    if isinstance(value, (int, float)):
        return 1 if value else 0

    normalized = clean_text(value).lower()
    return 1 if normalized in {"1", "true", "yes", "on", "y"} else 0


def coerce_copy_count(value: object | None, fallback: int = 1) -> int:
    if value is None or clean_text(value) == "":
        copy_count = int(fallback or 1)
    else:
        try:
            copy_count = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Copy count must be a whole number.") from error

    if copy_count < 1:
        raise ValueError("Copy count must be at least 1.")

    return copy_count


def serialize_book(book: sqlite3.Row | dict) -> dict:
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "isbn": book["isbn"],
        "cover_image_url": book["cover_image_url"],
        "stamped": bool(book["stamped"]),
        "copy_count": int(book["copy_count"]),
        "created_at": book["created_at"],
        "updated_at": book["updated_at"],
    }


def serialize_author_target(author_target: sqlite3.Row) -> dict:
    aliases = json.loads(author_target["aliases_json"]) if author_target["aliases_json"] else []
    return {
        "author_name": author_target["author_name"],
        "author_key": author_target["author_key"],
        "total_books": author_target["total_books"],
        "aliases": aliases,
        "sort_order": author_target["sort_order"],
        "source_url": author_target["source_url"],
        "updated_at": author_target["updated_at"],
    }


def author_matches(book_author: str, aliases: list[str]) -> bool:
    normalized_author = normalize_lookup_text(book_author)
    return any(normalize_lookup_text(alias) in normalized_author for alias in aliases)


def load_books(user_id: int) -> tuple[list[sqlite3.Row], bool]:
    if not DATABASE_PATH.exists():
        return [], False

    try:
        with get_db_connection() as connection:
            books = connection.execute(
                """
                SELECT id, user_id, title, author, isbn, cover_image_url, stamped, copy_count, created_at, updated_at
                FROM books
                WHERE user_id = ?
                ORDER BY title COLLATE NOCASE ASC
                """,
                (user_id,),
            ).fetchall()
        return books, True
    except sqlite3.OperationalError:
        return [], False


def load_author_targets(user_id: int) -> list[sqlite3.Row]:
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT user_id, author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
            FROM author_targets
            WHERE user_id = ?
            ORDER BY sort_order ASC, author_name COLLATE NOCASE ASC
            """,
            (user_id,),
        ).fetchall()


def load_user_summaries() -> list[dict]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                users.id,
                users.username,
                users.display_name,
                users.is_admin,
                users.created_at,
                users.last_login_at,
                COALESCE(SUM(books.copy_count), 0) AS book_count
            FROM users
            LEFT JOIN books ON books.user_id = users.id
            GROUP BY users.id
            ORDER BY users.display_name COLLATE NOCASE ASC, users.username COLLATE NOCASE ASC
            """
        ).fetchall()

    return [serialize_user_summary(row) for row in rows]


def build_author_progress(user_id: int, books: list[dict]) -> list[dict]:
    progress_rows = []

    for author_target in load_author_targets(user_id):
        serialized_target = serialize_author_target(author_target)
        aliases = serialized_target["aliases"] or [serialized_target["author_name"]]
        owned_books = sum(1 for book in books if author_matches(book["author"], aliases))
        total_books = serialized_target["total_books"]
        completion_percentage = (
            round((owned_books / total_books) * 100, 1) if total_books else 0.0
        )

        progress_rows.append(
            {
                **serialized_target,
                "owned_books": owned_books,
                "remaining_books": max(total_books - owned_books, 0),
                "completion_percentage": completion_percentage,
            }
        )

    return progress_rows


def build_library_payload(user: sqlite3.Row | dict) -> dict:
    user_id = int(user["id"])
    book_rows, database_ready = load_books(user_id)
    books = [serialize_book(book) for book in book_rows]
    payload = {
        "database_ready": database_ready,
        "books": books,
        "author_progress": build_author_progress(user_id, books),
        "current_user": serialize_current_user(user),
    }

    if bool(user["is_admin"]):
        payload["users"] = load_user_summaries()

    return payload


def prepare_book_fields(
    raw_book: dict,
    existing_book: sqlite3.Row | dict | None = None,
    *,
    preserve_existing_stamped: bool = False,
) -> dict:
    title = clean_text(
        raw_book["title"] if "title" in raw_book else existing_book["title"] if existing_book else ""
    )
    author = clean_text(
        raw_book["author"] if "author" in raw_book else existing_book["author"] if existing_book else ""
    )
    isbn = normalize_isbn(
        raw_book["isbn"] if "isbn" in raw_book else existing_book["isbn"] if existing_book else ""
    )
    cover_image_url = clean_text(
        raw_book["cover_image_url"]
        if "cover_image_url" in raw_book
        else existing_book["cover_image_url"] if existing_book else ""
    ) or None

    if not title:
        raise ValueError("Title is required.")

    if not author:
        raise ValueError("Author is required.")

    if existing_book and preserve_existing_stamped:
        stamped = existing_book["stamped"]
    else:
        stamped = coerce_stamped(
            raw_book["stamped"] if "stamped" in raw_book else existing_book["stamped"] if existing_book else False
        )

    copy_count = coerce_copy_count(
        raw_book["copy_count"] if "copy_count" in raw_book else existing_book["copy_count"] if existing_book else 1,
        fallback=existing_book["copy_count"] if existing_book else 1,
    )

    return {
        "title": title,
        "author": author,
        "isbn": isbn,
        "cover_image_url": cover_image_url,
        "stamped": stamped,
        "copy_count": copy_count,
    }


def fetch_book_by_id(connection: sqlite3.Connection, user_id: int, book_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, user_id, title, author, isbn, cover_image_url, stamped, copy_count, created_at, updated_at
        FROM books
        WHERE id = ? AND user_id = ?
        """,
        (book_id, user_id),
    ).fetchone()


def fetch_book_by_isbn(connection: sqlite3.Connection, user_id: int, isbn: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, user_id, title, author, isbn, cover_image_url, stamped, copy_count, created_at, updated_at
        FROM books
        WHERE isbn = ? AND user_id = ?
        """,
        (isbn, user_id),
    ).fetchone()


def upsert_book_record(
    connection: sqlite3.Connection,
    user_id: int,
    raw_book: dict,
    *,
    preserve_existing_stamped: bool = False,
) -> tuple[sqlite3.Row, bool]:
    existing_book = fetch_book_by_isbn(connection, user_id, normalize_isbn(raw_book.get("isbn")))
    prepared_book = prepare_book_fields(
        raw_book,
        existing_book,
        preserve_existing_stamped=preserve_existing_stamped,
    )
    now = utc_now_iso()

    if existing_book:
        connection.execute(
            """
            UPDATE books
            SET title = ?, author = ?, cover_image_url = ?, stamped = ?, copy_count = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                prepared_book["title"],
                prepared_book["author"],
                prepared_book["cover_image_url"],
                prepared_book["stamped"],
                prepared_book["copy_count"],
                now,
                existing_book["id"],
                user_id,
            ),
        )
        saved_book = fetch_book_by_id(connection, user_id, existing_book["id"])
        return saved_book, False

    cursor = connection.execute(
        """
        INSERT INTO books (user_id, title, author, isbn, cover_image_url, stamped, copy_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            prepared_book["title"],
            prepared_book["author"],
            prepared_book["isbn"],
            prepared_book["cover_image_url"],
            prepared_book["stamped"],
            prepared_book["copy_count"],
            now,
            now,
        ),
    )
    saved_book = fetch_book_by_id(connection, user_id, cursor.lastrowid)
    return saved_book, True


def update_book_record(
    connection: sqlite3.Connection,
    user_id: int,
    book_id: int,
    raw_updates: dict,
) -> sqlite3.Row:
    existing_book = fetch_book_by_id(connection, user_id, book_id)
    if existing_book is None:
        raise LookupError("Book not found.")

    prepared_book = prepare_book_fields(raw_updates, existing_book)
    connection.execute(
        """
        UPDATE books
        SET title = ?, author = ?, isbn = ?, cover_image_url = ?, stamped = ?, copy_count = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            prepared_book["title"],
            prepared_book["author"],
            prepared_book["isbn"],
            prepared_book["cover_image_url"],
            prepared_book["stamped"],
            prepared_book["copy_count"],
            utc_now_iso(),
            book_id,
            user_id,
        ),
    )
    return fetch_book_by_id(connection, user_id, book_id)


def increment_book_copy_count(
    connection: sqlite3.Connection,
    user_id: int,
    book_id: int,
) -> sqlite3.Row:
    connection.execute(
        """
        UPDATE books
        SET copy_count = copy_count + 1, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (utc_now_iso(), book_id, user_id),
    )
    updated_book = fetch_book_by_id(connection, user_id, book_id)
    if updated_book is None:
        raise LookupError("Book not found.")
    return updated_book


def delete_book_record(connection: sqlite3.Connection, user_id: int, book_id: int) -> bool:
    cursor = connection.execute(
        "DELETE FROM books WHERE id = ? AND user_id = ?",
        (book_id, user_id),
    )
    return cursor.rowcount > 0


def fetch_book_from_open_library(isbn: str) -> dict | None:
    query_string = urlencode(
        {
            "bibkeys": f"ISBN:{isbn}",
            "format": "json",
            "jscmd": "data",
        }
    )
    request_url = f"{OPEN_LIBRARY_BOOKS_API}?{query_string}"

    with urlopen(request_url, timeout=10) as response:
        payload = json.load(response)

    book_data = payload.get(f"ISBN:{isbn}")
    if not book_data or not book_data.get("title"):
        return None

    authors = ", ".join(
        author["name"]
        for author in book_data.get("authors", [])
        if author.get("name")
    )
    cover_data = book_data.get("cover") or {}
    cover_image_url = cover_data.get("large") or cover_data.get("medium") or cover_data.get("small")

    return {
        "title": book_data["title"].strip(),
        "author": authors or "Unknown author",
        "isbn": isbn,
        "cover_image_url": cover_image_url,
    }


def parse_author_targets_from_import(import_payload: object) -> list[dict]:
    if not isinstance(import_payload, list):
        return []

    parsed_targets = []
    for position, target in enumerate(import_payload, start=1):
        if not isinstance(target, dict):
            raise ValueError("Imported author progress targets must be objects.")

        author_name = clean_text(target.get("author_name"))
        if not author_name:
            raise ValueError("Imported author progress target is missing an author_name.")

        total_books = int(target.get("total_books", 0))
        if total_books < 0:
            raise ValueError("Imported author progress total_books must be 0 or greater.")

        aliases = target.get("aliases")
        if not isinstance(aliases, list) or not aliases:
            aliases = [author_name]

        parsed_targets.append(
            {
                "author_name": author_name,
                "author_key": clean_text(target.get("author_key")) or None,
                "total_books": total_books,
                "aliases": [clean_text(alias) for alias in aliases if clean_text(alias)],
                "sort_order": int(target.get("sort_order", position)),
                "source_url": clean_text(target.get("source_url")) or None,
                "updated_at": clean_text(target.get("updated_at")) or utc_now_iso(),
            }
        )

    return parsed_targets


def parse_books_from_import(import_payload: object) -> list[dict]:
    if isinstance(import_payload, list):
        books_payload = import_payload
    elif isinstance(import_payload, dict) and isinstance(import_payload.get("books"), list):
        books_payload = import_payload["books"]
    else:
        raise ValueError("Import files must contain a top-level books array.")

    parsed_books = []
    for book in books_payload:
        if not isinstance(book, dict):
            raise ValueError("Imported books must be JSON objects.")

        parsed_books.append(
            {
                "title": book.get("title", ""),
                "author": book.get("author", ""),
                "isbn": book.get("isbn", ""),
                "cover_image_url": book.get("cover_image_url", ""),
                "stamped": book.get("stamped", False),
                "copy_count": book.get("copy_count", 1),
            }
        )

    return parsed_books


def export_library_json_response(user: sqlite3.Row | dict) -> Response:
    payload = build_library_payload(user)
    payload.update(
        {
            "exported_at": utc_now_iso(),
            "version": 4,
            "account": serialize_current_user(user),
            "author_targets": [
                serialize_author_target(target)
                for target in load_author_targets(int(user["id"]))
            ],
        }
    )
    payload.pop("users", None)

    response = Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
    )
    response.headers["Content-Disposition"] = "attachment; filename=home-library-backup.json"
    return response


def export_library_csv_response(user: sqlite3.Row | dict) -> Response:
    payload = build_library_payload(user)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["title", "author", "isbn", "cover_image_url", "stamped", "copy_count"],
    )
    writer.writeheader()
    for book in payload["books"]:
        writer.writerow(
            {
                "title": book["title"],
                "author": book["author"],
                "isbn": book["isbn"],
                "cover_image_url": book["cover_image_url"] or "",
                "stamped": "true" if book["stamped"] else "false",
                "copy_count": book["copy_count"],
            }
        )

    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=home-library-export.csv"
    return response


@app.get("/healthz")
def healthcheck():
    return {"status": "ok"}


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    next_target = request.args.get("next") or request.form.get("next") or url_for("index")
    next_url = next_target if is_safe_redirect_target(next_target) else url_for("index")
    error_message = None

    if request.method == "POST":
        submitted_username = normalize_username(request.form.get("username"))
        submitted_password = request.form.get("password", "")

        with get_db_connection() as connection:
            user = fetch_user_by_username(connection, submitted_username) if submitted_username else None
            if user and verify_password(submitted_password, user["password_hash"]):
                update_user_last_login(connection, user["id"])
                session.clear()
                session["user_id"] = int(user["id"])
                return redirect(next_url)

        error_message = "That username and password combination was not correct."

    return render_template(
        "login.html",
        error_message=error_message,
        next_url=next_url,
        default_admin_username=DEFAULT_ADMIN_USERNAME,
    )


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    payload = build_library_payload(g.current_user)
    return render_template("index.html", initial_data=payload)


@app.route("/api/books")
def get_books():
    return build_library_payload(g.current_user)


@app.get("/api/author-progress")
def get_author_progress():
    return {"author_progress": build_library_payload(g.current_user)["author_progress"]}


@app.get("/api/users")
def get_users():
    if not bool(g.current_user["is_admin"]):
        return admin_required_response()

    return {"users": load_user_summaries()}


@app.post("/api/users")
def create_user_account():
    if not bool(g.current_user["is_admin"]):
        return admin_required_response()

    payload = request.get_json(silent=True) or {}

    try:
        with get_db_connection() as connection:
            created_user = create_user(
                connection,
                username=payload.get("username"),
                display_name=payload.get("display_name"),
                password=payload.get("password"),
                is_admin=bool(payload.get("is_admin")),
            )
    except ValueError as error:
        return {"error": str(error)}, 400

    response_payload = build_library_payload(g.current_user)
    response_payload.update(
        {
            "message": (
                f"Created a separate library account for {created_user['display_name']} "
                f"(@{created_user['username']})."
            ),
            "user": serialize_user_summary(created_user),
        }
    )
    return response_payload, 201


@app.post("/api/books/scan")
def scan_book():
    payload = request.get_json(silent=True) or {}
    raw_isbn = payload.get("isbn", "")
    duplicate_decision = clean_text(payload.get("duplicate_decision")).lower()

    try:
        isbn = normalize_isbn(raw_isbn)
    except ValueError as error:
        return {"error": str(error)}, 400

    if duplicate_decision and duplicate_decision != "additional_copy":
        return {"error": "Duplicate decision must be additional_copy when provided."}, 400

    user_id = int(g.current_user["id"])

    with get_db_connection() as connection:
        existing_book = fetch_book_by_isbn(connection, user_id, isbn)
        if existing_book is not None:
            current_copy_count = int(existing_book["copy_count"])
            if duplicate_decision != "additional_copy":
                return {
                    "requires_confirmation": True,
                    "book": serialize_book(existing_book),
                    "message": (
                        f"{existing_book['title']} is already in your catalogue with "
                        f"{current_copy_count} {'copy' if current_copy_count == 1 else 'copies'}. "
                        "Is this an additional copy?"
                    ),
                }

            updated_book = increment_book_copy_count(connection, user_id, existing_book["id"])
            response_payload = build_library_payload(g.current_user)
            response_payload.update(
                {
                    "book": serialize_book(updated_book),
                    "created": False,
                    "additional_copy_added": True,
                    "message": (
                        f"Added another copy of {updated_book['title']}. "
                        f"You now have {updated_book['copy_count']} "
                        f"{'copy' if updated_book['copy_count'] == 1 else 'copies'}."
                    ),
                }
            )
            return response_payload

    try:
        metadata = fetch_book_from_open_library(isbn)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {
            "error": "Open Library could not be reached. Please try again in a moment.",
        }, 502

    if metadata is None:
        return {"error": f"No book details were found for ISBN {isbn}."}, 404

    with get_db_connection() as connection:
        saved_book, created = upsert_book_record(
            connection,
            user_id,
            metadata,
            preserve_existing_stamped=True,
        )

    response_payload = build_library_payload(g.current_user)
    response_payload.update(
        {
            "book": serialize_book(saved_book),
            "created": created,
            "message": (
                f"Added {saved_book['title']} to {g.current_user['display_name']}'s catalogue."
                if created
                else f"Updated {saved_book['title']} in {g.current_user['display_name']}'s catalogue."
            ),
        }
    )
    return response_payload, 201 if created else 200


@app.patch("/api/books/<int:book_id>")
def update_book(book_id: int):
    payload = request.get_json(silent=True) or {}

    try:
        with get_db_connection() as connection:
            updated_book = update_book_record(connection, int(g.current_user["id"]), book_id, payload)
    except LookupError:
        return {"error": "Book not found."}, 404
    except ValueError as error:
        return {"error": str(error)}, 400
    except sqlite3.IntegrityError:
        return {"error": "That ISBN already belongs to another book in your catalogue."}, 409

    response_payload = build_library_payload(g.current_user)
    response_payload.update(
        {
            "book": serialize_book(updated_book),
            "message": f"Saved changes to {updated_book['title']}.",
        }
    )
    return response_payload


@app.delete("/api/books/<int:book_id>")
def delete_book(book_id: int):
    with get_db_connection() as connection:
        deleted = delete_book_record(connection, int(g.current_user["id"]), book_id)

    if not deleted:
        return {"error": "Book not found."}, 404

    response_payload = build_library_payload(g.current_user)
    response_payload.update({"message": "Deleted the book from your catalogue."})
    return response_payload


@app.get("/api/library/export.json")
def export_json():
    return export_library_json_response(g.current_user)


@app.get("/api/library/export.csv")
def export_csv():
    return export_library_csv_response(g.current_user)


@app.post("/api/library/import")
def import_library_backup():
    import_file = request.files.get("file")
    mode = clean_text(request.form.get("mode", "merge")).lower() or "merge"

    if import_file is None or not import_file.filename:
        return {"error": "Choose a JSON backup file to import."}, 400

    if mode not in {"merge", "replace"}:
        return {"error": "Import mode must be merge or replace."}, 400

    try:
        import_payload = json.loads(import_file.stream.read().decode("utf-8"))
        parsed_books = parse_books_from_import(import_payload)
        parsed_author_targets = parse_author_targets_from_import(
            import_payload.get("author_targets", []) if isinstance(import_payload, dict) else []
        )
    except UnicodeDecodeError:
        return {"error": "Import files must be UTF-8 encoded JSON."}, 400
    except json.JSONDecodeError:
        return {"error": "Import files must be valid JSON."}, 400
    except ValueError as error:
        return {"error": str(error)}, 400

    created_count = 0
    updated_count = 0
    user_id = int(g.current_user["id"])

    try:
        with get_db_connection() as connection:
            if mode == "replace":
                connection.execute("DELETE FROM books WHERE user_id = ?", (user_id,))
                if parsed_author_targets:
                    connection.execute("DELETE FROM author_targets WHERE user_id = ?", (user_id,))

            if parsed_author_targets:
                seed_author_targets(
                    connection,
                    user_id=user_id,
                    overwrite=True,
                    targets=parsed_author_targets,
                )

            for parsed_book in parsed_books:
                _, created = upsert_book_record(
                    connection,
                    user_id,
                    parsed_book,
                    preserve_existing_stamped=False,
                )
                created_count += 1 if created else 0
                updated_count += 0 if created else 1
    except (ValueError, sqlite3.IntegrityError) as error:
        return {"error": f"Import failed: {error}"}, 400

    response_payload = build_library_payload(g.current_user)
    response_payload.update(
        {
            "message": (
                f"Imported {created_count + updated_count} books into your library "
                f"({created_count} created, {updated_count} updated)."
            )
        }
    )
    return response_payload


if __name__ == "__main__":
    app.run(
        host=HOST,
        port=PORT,
        debug=FLASK_DEBUG or os.environ.get("FLASK_ENV") == "development",
    )
