import sqlite3

from init_db import initialize_database, seed_author_targets
from settings import DATABASE_PATH


if __name__ == "__main__":
    initialize_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        updated_count = seed_author_targets(connection, overwrite=True)
        connection.commit()

    print(f"Updated {updated_count} author progress targets in {DATABASE_PATH}")
