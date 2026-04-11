CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    isbn TEXT NOT NULL UNIQUE,
    cover_image_url TEXT,
    stamped INTEGER NOT NULL DEFAULT 0 CHECK (stamped IN (0, 1))
);
