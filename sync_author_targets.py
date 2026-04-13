from init_db import create_connection, initialize_database, seed_author_targets_for_all_users
from settings import DATABASE_PATH


if __name__ == "__main__":
    initialize_database()

    with create_connection(DATABASE_PATH) as connection:
        updated_count = seed_author_targets_for_all_users(connection, overwrite=True)
        connection.commit()

    print(f"Updated {updated_count} author progress targets across all users in {DATABASE_PATH}")
