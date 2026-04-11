import sqlite3

from settings import DATABASE_PATH, SCHEMA_PATH


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialised at {DATABASE_PATH}")
