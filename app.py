import hmac
import json
import os
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import Flask, redirect, render_template, request, session, url_for

from init_db import initialize_database
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

# Ensure the configured database path exists before the first request.
initialize_database()

EXEMPT_ENDPOINTS = {"healthcheck", "login", "logout", "static"}


def is_safe_redirect_target(target: str | None) -> bool:
    return bool(target) and target.startswith("/") and not target.startswith("//")


def authentication_required_response():
    if request.path.startswith("/api/"):
        return {"error": "Authentication required."}, 401

    next_target = request.full_path if request.query_string else request.path
    return redirect(url_for("login", next=next_target))


@app.before_request
def require_authentication():
    if request.endpoint in EXEMPT_ENDPOINTS:
        return None

    if session.get("authenticated") is True:
        return None

    return authentication_required_response()


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def serialize_book(book: sqlite3.Row) -> dict:
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "isbn": book["isbn"],
        "cover_image_url": book["cover_image_url"],
        "stamped": bool(book["stamped"]),
    }


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


def get_books_payload() -> dict:
    books, database_ready = load_books()
    return {
        "database_ready": database_ready,
        "books": [serialize_book(book) for book in books],
    }


def normalize_isbn(raw_isbn: str) -> str:
    normalized = "".join(
        character
        for character in (raw_isbn or "").upper()
        if character.isdigit() or character == "X"
    )

    if len(normalized) not in {10, 13}:
        raise ValueError("ISBN scans must contain 10 or 13 characters.")

    return normalized


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


def save_book(metadata: dict) -> tuple[sqlite3.Row, bool]:
    initialize_database()

    with get_db_connection() as connection:
        existing_book = connection.execute(
            """
            SELECT id, title, author, isbn, cover_image_url, stamped
            FROM books
            WHERE isbn = ?
            """,
            (metadata["isbn"],),
        ).fetchone()

        if existing_book:
            title = metadata["title"] or existing_book["title"]
            author = metadata["author"] or existing_book["author"]
            cover_image_url = (
                metadata["cover_image_url"] or existing_book["cover_image_url"]
            )
            connection.execute(
                """
                UPDATE books
                SET title = ?, author = ?, cover_image_url = ?
                WHERE id = ?
                """,
                (title, author, cover_image_url, existing_book["id"]),
            )
            book_id = existing_book["id"]
            created = False
        else:
            cursor = connection.execute(
                """
                INSERT INTO books (title, author, isbn, cover_image_url, stamped)
                VALUES (?, ?, ?, ?, 0)
                """,
                (
                    metadata["title"],
                    metadata["author"],
                    metadata["isbn"],
                    metadata["cover_image_url"],
                ),
            )
            book_id = cursor.lastrowid
            created = True

        saved_book = connection.execute(
            """
            SELECT id, title, author, isbn, cover_image_url, stamped
            FROM books
            WHERE id = ?
            """,
            (book_id,),
        ).fetchone()

    return saved_book, created


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
    payload = get_books_payload()
    return render_template(
        "index.html",
        books_data=payload["books"],
        database_ready=payload["database_ready"],
    )


@app.route("/api/books")
def get_books():
    return get_books_payload()


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

    saved_book, created = save_book(metadata)
    response_payload = get_books_payload()
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


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=FLASK_DEBUG or os.environ.get("FLASK_ENV") == "development")
