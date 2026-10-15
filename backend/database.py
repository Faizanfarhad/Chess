"""Small PostgreSQL repository for accounts, games, and ranked matchmaking."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
import json


DATABASE_URL = os.getenv("DATABASE_URL", "")
PBKDF2_ITERATIONS = 600_000


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured. Set it to your PostgreSQL connection URL.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as error:
        raise RuntimeError("Install psycopg[binary] before starting the backend.") from error
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_database() -> None:
    """Create the small set of tables needed by the application."""

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    rating INTEGER NOT NULL DEFAULT 1200,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_unique ON users (LOWER(username))")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    room_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    time_control INTEGER NOT NULL,
                    state JSONB NOT NULL,
                    white_user_id BIGINT REFERENCES users(id),
                    black_user_id BIGINT REFERENCES users(id),
                    rating_recorded BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("ALTER TABLE games ADD COLUMN IF NOT EXISTS rating_recorded BOOLEAN NOT NULL DEFAULT FALSE")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS matchmaking_queue (
                    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    rating INTEGER NOT NULL,
                    time_control INTEGER NOT NULL,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    matched_game_id TEXT
                )
            """)


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    ).hex()


def create_user(username: str, password: str) -> dict:
    username = username.strip()
    if len(username) < 3 or len(username) > 30:
        raise ValueError("Username must be between 3 and 30 characters.")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")

    salt = secrets.token_bytes(16)
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, password_salt) VALUES (%s, %s, %s) RETURNING id, username, rating",
                    (username, _password_hash(password, salt), salt.hex()),
                )
                user = cursor.fetchone()
    except Exception as error:
        if "unique" in str(error).lower() or "duplicate" in str(error).lower():
            raise ValueError("That username is already taken.") from error
        raise
    return dict(user)


def authenticate_user(username: str, password: str) -> dict | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, username, rating, password_hash, password_salt FROM users WHERE LOWER(username) = LOWER(%s)", (username.strip(),))
            user = cursor.fetchone()
    if not user:
        return None
    expected = _password_hash(password, bytes.fromhex(user["password_salt"]))
    if not hmac.compare_digest(expected, user["password_hash"]):
        return None
    return {"id": user["id"], "username": user["username"], "rating": user["rating"]}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO sessions (token_hash, user_id) VALUES (%s, %s)", (token_hash, user_id))
    return token


def get_user_by_token(token: str | None) -> dict | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT users.id, users.username, users.rating
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = %s
            """, (token_hash,))
            user = cursor.fetchone()
    return dict(user) if user else None


def get_user_by_id(user_id: int | None) -> dict | None:
    """Return the public account details needed when displaying a player."""

    if user_id is None:
        return None
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, username, rating FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
    return dict(user) if user else None


def save_game(room_id: str, mode: str, time_control: int, state: dict, white_user_id=None, black_user_id=None) -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO games (room_id, mode, time_control, state, white_user_id, black_user_id)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (room_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    mode = EXCLUDED.mode,
                    time_control = EXCLUDED.time_control,
                    white_user_id = COALESCE(EXCLUDED.white_user_id, games.white_user_id),
                    black_user_id = COALESCE(EXCLUDED.black_user_id, games.black_user_id),
                    updated_at = NOW()
            """, (room_id, mode, time_control, json.dumps(state), white_user_id, black_user_id))


def load_game(room_id: str) -> dict | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM games WHERE room_id = %s", (room_id,))
            row = cursor.fetchone()
    return dict(row) if row else None


def enqueue_match(user: dict, time_control: int) -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO matchmaking_queue (user_id, rating, time_control, matched_game_id)
                VALUES (%s, %s, %s, NULL)
                ON CONFLICT (user_id) DO UPDATE SET rating = EXCLUDED.rating, time_control = EXCLUDED.time_control, joined_at = NOW(), matched_game_id = NULL
            """, (user["id"], user["rating"], time_control))


def find_match(user: dict, time_control: int) -> dict | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT user_id, rating, time_control
                FROM matchmaking_queue
                WHERE user_id <> %s AND time_control = %s AND matched_game_id IS NULL
                  AND rating BETWEEN %s AND %s
                ORDER BY ABS(rating - %s), joined_at
                LIMIT 1
            """, (user["id"], time_control, user["rating"] - 200, user["rating"] + 200, user["rating"]))
            row = cursor.fetchone()
    return dict(row) if row else None


def mark_match(user_id: int, game_id: str) -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE matchmaking_queue SET matched_game_id = %s WHERE user_id = %s", (game_id, user_id))


def matchmaking_status(user_id: int) -> dict | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM matchmaking_queue WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
    return dict(row) if row else None


def leave_matchmaking(user_id: int) -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM matchmaking_queue WHERE user_id = %s", (user_id,))


def record_ranked_result(room_id: str, winner: str | None) -> dict:
    """Apply Elo once and return each player's before/after rating."""

    if winner not in {"w", "b"}:
        return {}
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT mode, white_user_id, black_user_id, rating_recorded FROM games WHERE room_id = %s FOR UPDATE", (room_id,))
            game = cursor.fetchone()
            if not game or game["mode"] != "ranked" or game["rating_recorded"] or not game["white_user_id"] or not game["black_user_id"]:
                return {}
            cursor.execute("SELECT id, rating FROM users WHERE id IN (%s, %s) FOR UPDATE", (game["white_user_id"], game["black_user_id"]))
            ratings = {row["id"]: row["rating"] for row in cursor.fetchall()}
            white_rating = ratings[game["white_user_id"]]
            black_rating = ratings[game["black_user_id"]]
            expected_white = 1 / (1 + 10 ** ((black_rating - white_rating) / 400))
            score_white = 1 if winner == "w" else 0
            delta = round(32 * (score_white - expected_white))
            white_after = white_rating + delta
            black_after = black_rating - delta
            cursor.execute("UPDATE users SET rating = %s WHERE id = %s", (white_after, game["white_user_id"]))
            cursor.execute("UPDATE users SET rating = %s WHERE id = %s", (black_after, game["black_user_id"]))
            cursor.execute("UPDATE games SET rating_recorded = TRUE WHERE room_id = %s", (room_id,))
    return {
        "w": {"before": white_rating, "after": white_after, "change": delta},
        "b": {"before": black_rating, "after": black_after, "change": -delta},
    }
