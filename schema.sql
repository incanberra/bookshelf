CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    isbn TEXT NOT NULL UNIQUE,
    cover_image_url TEXT,
    stamped INTEGER NOT NULL DEFAULT 0 CHECK (stamped IN (0, 1))
);

CREATE TABLE IF NOT EXISTS author_targets (
    author_name TEXT PRIMARY KEY,
    author_key TEXT,
    total_books INTEGER NOT NULL CHECK (total_books >= 0),
    aliases_json TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    updated_at TEXT NOT NULL
);
