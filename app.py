import csv
from datetime import datetime, timezone
import hmac
import io
import json
import os
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import Flask, Response, redirect, render_template, request, session, url_for

from init_db import initialize_database, seed_author_targets
from settings import (
    APP_PASSWORD,
    DATABASE_PATH,
    FLASK_DEBUG,
    HOST,
    OPEN_LIBRARY_BOOKS_API,
    PORT,
    SECRET_KEY,
    SESSION_COOKIE_SECURE,
)


if not APP_PASSWORD:
    raise RuntimeError("APP_PASSWORD must be set before starting the app.")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set before starting the app.")


app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
)

# Ensure the configured database path and seeded author progress targets exist.
initialize_database()

EXEMPT_ENDPOINTS = {"healthcheck", "login", "logout", "static"}
BOOK_FIELDS = ("id", "title", "author", "isbn", "cover_image_url", "stamped")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_safe_redirect_target(target: str | None) -> bool:
    return bool(target) and target.startswith("/") and not target.startswith("//")


def authentication_required_response():
    if request.path.startswith("/api/"):
        return {"error": "Authentication required."}, 401

    next_target = request.full_path.rstrip("?") if request.query_string else request.path
    return redirect(url_for("login", next=next_target))


@app.before_request
def require_authentication():
    if request.endpoint is None or request.endpoint in EXEMPT_ENDPOINTS:
        return None

    if session.get("authenticated") is True:
        return None

    return authentication_required_response()


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def clean_text(value: object | None) -> str:
    return " ".join(str(value or "").strip().split())


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


def serialize_book(book: sqlite3.Row | dict) -> dict:
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "isbn": book["isbn"],
        "cover_image_url": book["cover_image_url"],
        "stamped": bool(book["stamped"]),
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


def load_books() -> tuple[list[sqlite3.Row], bool]:
    if not DATABASE_PATH.exists():
        return [], False

    try:
        with get_db_connection() as connection:
            books = connection.execute(
                """
                SELECT id, title, author, isbn, cover_image_url, stamped
                FROM books
                ORDER BY title COLLATE NOCASE ASC
                """
            ).fetchall()
        return books, True
    except sqlite3.OperationalError:
        return [], False


def load_author_targets() -> list[sqlite3.Row]:
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
            FROM author_targets
            ORDER BY sort_order ASC, author_name COLLATE NOCASE ASC
            """
        ).fetchall()


def build_author_progress(books: list[dict]) -> list[dict]:
    progress_rows = []

    for author_target in load_author_targets():
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


def build_library_payload() -> dict:
    book_rows, database_ready = load_books()
    books = [serialize_book(book) for book in book_rows]
    return {
        "database_ready": database_ready,
        "books": books,
        "author_progress": build_author_progress(books),
    }


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

    return {
        "title": title,
        "author": author,
        "isbn": isbn,
        "cover_image_url": cover_image_url,
        "stamped": stamped,
    }


def fetch_book_by_id(connection: sqlite3.Connection, book_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, title, author, isbn, cover_image_url, stamped
        FROM books
        WHERE id = ?
        """,
        (book_id,),
    ).fetchone()


def fetch_book_by_isbn(connection: sqlite3.Connection, isbn: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, title, author, isbn, cover_image_url, stamped
        FROM books
        WHERE isbn = ?
        """,
        (isbn,),
    ).fetchone()


def upsert_book_record(
    connection: sqlite3.Connection,
    raw_book: dict,
    *,
    preserve_existing_stamped: bool = False,
) -> tuple[sqlite3.Row, bool]:
    existing_book = fetch_book_by_isbn(connection, normalize_isbn(raw_book.get("isbn")))
    prepared_book = prepare_book_fields(
        raw_book,
        existing_book,
        preserve_existing_stamped=preserve_existing_stamped,
    )

    if existing_book:
        connection.execute(
            """
            UPDATE books
            SET title = ?, author = ?, cover_image_url = ?, stamped = ?
            WHERE id = ?
            """,
            (
                prepared_book["title"],
                prepared_book["author"],
                prepared_book["cover_image_url"],
                prepared_book["stamped"],
                existing_book["id"],
            ),
        )
        saved_book = fetch_book_by_id(connection, existing_book["id"])
        return saved_book, False

    cursor = connection.execute(
        """
        INSERT INTO books (title, author, isbn, cover_image_url, stamped)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            prepared_book["title"],
            prepared_book["author"],
            prepared_book["isbn"],
            prepared_book["cover_image_url"],
            prepared_book["stamped"],
        ),
    )
    saved_book = fetch_book_by_id(connection, cursor.lastrowid)
    return saved_book, True


def update_book_record(connection: sqlite3.Connection, book_id: int, raw_updates: dict) -> sqlite3.Row:
    existing_book = fetch_book_by_id(connection, book_id)
    if existing_book is None:
        raise LookupError("Book not found.")

    prepared_book = prepare_book_fields(raw_updates, existing_book)
    connection.execute(
        """
        UPDATE books
        SET title = ?, author = ?, isbn = ?, cover_image_url = ?, stamped = ?
        WHERE id = ?
        """,
        (
            prepared_book["title"],
            prepared_book["author"],
            prepared_book["isbn"],
            prepared_book["cover_image_url"],
            prepared_book["stamped"],
            book_id,
        ),
    )
    return fetch_book_by_id(connection, book_id)


def delete_book_record(connection: sqlite3.Connection, book_id: int) -> bool:
    cursor = connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
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
    cover_image_url = (
        cover_data.get("large")
        or cover_data.get("medium")
        or cover_data.get("small")
    )

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
            }
        )

    return parsed_books


def export_library_json_response() -> Response:
    payload = build_library_payload()
    payload.update(
        {
            "exported_at": utc_now_iso(),
            "version": 2,
            "author_targets": [serialize_author_target(target) for target in load_author_targets()],
        }
    )

    response = Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
    )
    response.headers["Content-Disposition"] = "attachment; filename=home-library-backup.json"
    return response


def export_library_csv_response() -> Response:
    payload = build_library_payload()
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["title", "author", "isbn", "cover_image_url", "stamped"],
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
    if session.get("authenticated") is True:
        return redirect(url_for("index"))

    next_target = request.args.get("next") or request.form.get("next") or url_for("index")
    next_url = next_target if is_safe_redirect_target(next_target) else url_for("index")
    error_message = None

    if request.method == "POST":
        submitted_password = request.form.get("password", "")
        if hmac.compare_digest(submitted_password, APP_PASSWORD):
            session.clear()
            session["authenticated"] = True
            return redirect(next_url)

        error_message = "That password was not correct."

    return render_template("login.html", error_message=error_message, next_url=next_url)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    payload = build_library_payload()
    return render_template("index.html", initial_data=payload)


@app.route("/api/books")
def get_books():
    return build_library_payload()


@app.get("/api/author-progress")
def get_author_progress():
    return {"author_progress": build_library_payload()["author_progress"]}


@app.post("/api/books/scan")
def scan_book():
    payload = request.get_json(silent=True) or {}
    raw_isbn = payload.get("isbn", "")

    try:
        isbn = normalize_isbn(raw_isbn)
    except ValueError as error:
        return {"error": str(error)}, 400

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
            metadata,
            preserve_existing_stamped=True,
        )

    response_payload = build_library_payload()
    response_payload.update(
        {
            "book": serialize_book(saved_book),
            "created": created,
            "message": (
                f"Added {saved_book['title']} to your catalogue."
                if created
                else f"Updated {saved_book['title']} in your catalogue."
            ),
        }
    )
    return response_payload, 201 if created else 200


@app.patch("/api/books/<int:book_id>")
def update_book(book_id: int):
    payload = request.get_json(silent=True) or {}

    try:
        with get_db_connection() as connection:
            updated_book = update_book_record(connection, book_id, payload)
    except LookupError:
        return {"error": "Book not found."}, 404
    except ValueError as error:
        return {"error": str(error)}, 400
    except sqlite3.IntegrityError:
        return {"error": "That ISBN already belongs to another book in your catalogue."}, 409

    response_payload = build_library_payload()
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
        deleted = delete_book_record(connection, book_id)

    if not deleted:
        return {"error": "Book not found."}, 404

    response_payload = build_library_payload()
    response_payload.update({"message": "Deleted the book from your catalogue."})
    return response_payload


@app.get("/api/library/export.json")
def export_json():
    return export_library_json_response()


@app.get("/api/library/export.csv")
def export_csv():
    return export_library_csv_response()


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

    try:
        with get_db_connection() as connection:
            if mode == "replace":
                connection.execute("DELETE FROM books")
                if parsed_author_targets:
                    connection.execute("DELETE FROM author_targets")

            if parsed_author_targets:
                seed_author_targets(
                    connection,
                    overwrite=True,
                    targets=parsed_author_targets,
                )

            for parsed_book in parsed_books:
                _, created = upsert_book_record(
                    connection,
                    parsed_book,
                    preserve_existing_stamped=False,
                )
                created_count += 1 if created else 0
                updated_count += 0 if created else 1
    except (ValueError, sqlite3.IntegrityError) as error:
        return {"error": f"Import failed: {error}"}, 400

    response_payload = build_library_payload()
    response_payload.update(
        {
            "message": (
                f"Imported {created_count + updated_count} books "
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
