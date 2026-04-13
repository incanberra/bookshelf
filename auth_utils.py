import base64
import hashlib
import hmac
import secrets


DEFAULT_HASH_ITERATIONS = 390000


def hash_password(password: str, *, iterations: int = DEFAULT_HASH_ITERATIONS) -> str:
    if not isinstance(password, str):
        raise TypeError("Passwords must be strings.")

    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    encoded_salt = base64.b64encode(salt).decode("ascii")
    encoded_key = base64.b64encode(derived_key).decode("ascii")
    return f"pbkdf2_sha256${iterations}${encoded_salt}${encoded_key}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iteration_text, encoded_salt, encoded_key = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iteration_text)
        salt = base64.b64decode(encoded_salt.encode("ascii"))
        expected_key = base64.b64decode(encoded_key.encode("ascii"))
    except (ValueError, TypeError):
        return False

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(derived_key, expected_key)
