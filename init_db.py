import json
import sqlite3
from datetime import datetime, timezone

from library_defaults import AUTHOR_PROGRESS_DEFAULTS
from settings import DATABASE_PATH, SCHEMA_PATH


def seed_author_targets(
    connection: sqlite3.Connection,
    *,
    overwrite: bool = False,
    targets: list[dict] | tuple[dict, ...] | None = None,
) -> int:
    seeded_count = 0
    active_targets = list(targets or AUTHOR_PROGRESS_DEFAULTS)

    for position, target in enumerate(active_targets, start=1):
        author_name = " ".join(str(target["author_name"]).strip().split())
        aliases = target.get("aliases") or [author_name]
        payload = (
            author_name,
            target.get("author_key"),
            int(target["total_books"]),
            json.dumps(aliases, ensure_ascii=False),
            int(target.get("sort_order", position)),
            target.get("source_url"),
            target.get("updated_at") or datetime.now(timezone.utc).isoformat(),
        )

        if overwrite:
            connection.execute(
                """
                INSERT INTO author_targets (
                    author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(author_name) DO UPDATE SET
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
                author_name, author_key, total_books, aliases_json, sort_order, source_url, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        seeded_count += connection.execute("SELECT changes()").fetchone()[0]

    return seeded_count


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        seed_author_targets(connection)
        connection.commit()


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialised at {DATABASE_PATH}")
