CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

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
);

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
);

CREATE INDEX IF NOT EXISTS idx_books_user_id_title
ON books (user_id, title COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_books_user_id_author
ON books (user_id, author COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_author_targets_user_id_sort
ON author_targets (user_id, sort_order, author_name COLLATE NOCASE);
