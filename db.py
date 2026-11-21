"""Tiny SQLite helper shared by the web app and the user-management script."""
import sqlite3
from pathlib import Path

import settings

BASE_DIR = settings.BASE_DIR
INSTANCE_DIR = settings.DATA_DIR            # database, secret key, avatars (env DATA_DIR)
DB_PATH = INSTANCE_DIR / "cards.db"
AVATAR_DIR = INSTANCE_DIR / "avatars"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,          -- scrypt hash with salt, never the plain password
    avatar        TEXT,                      -- filename of the profile pic in instance/avatars
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id TEXT    NOT NULL,             -- = file name of the subject JSON (without .json)
    card_id    TEXT    NOT NULL,             -- = "id" of the card inside that JSON
    parent_id  INTEGER REFERENCES comments(id),   -- NULL = top-level comment, else a reply
    user_id    INTEGER NOT NULL REFERENCES users(id),
    body       TEXT    NOT NULL,
    deleted    INTEGER NOT NULL DEFAULT 0,   -- soft delete, so replies keep their parent
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_comments_card ON comments(subject_id, card_id);

CREATE TABLE IF NOT EXISTS flags (           -- cards a user is not sure about ("Flagged")
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id TEXT    NOT NULL,
    card_id    TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, subject_id, card_id)
);

CREATE TABLE IF NOT EXISTS login_failures (  -- brute-force protection, shared by all worker processes
    key   TEXT    PRIMARY KEY,                -- "u:<ip>|<username>" or "ip:<ip>"
    count INTEGER NOT NULL,
    last  INTEGER NOT NULL                    -- unix time of the last failure
);

CREATE TABLE IF NOT EXISTS presence (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    activity   TEXT    NOT NULL,             -- idle | browsing | studying | practising
    subject_id TEXT,
    last_seen  INTEGER NOT NULL              -- unix time of the last heartbeat
);
"""

# columns added after the first version of the app (see _migrate)
USER_COLUMNS = {
    "is_admin": "INTEGER NOT NULL DEFAULT 0",
    "is_banned": "INTEGER NOT NULL DEFAULT 0",
    "must_change_password": "INTEGER NOT NULL DEFAULT 0",
    "language": "TEXT",                                    # en | sk | cs (NULL = not chosen yet)
    "status": "TEXT NOT NULL DEFAULT 'online'",            # online | idle | dnd | invisible
    "status_text": "TEXT NOT NULL DEFAULT ''",             # optional custom status message
}


def connect() -> sqlite3.Connection:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)         # wait up to 10 s if another worker is writing
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")           # readers don't block the writer (several workers)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    for name, definition in USER_COLUMNS.items():
        if name not in cols:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            except sqlite3.OperationalError as e:       # another worker was faster
                if "duplicate column" not in str(e):
                    raise


def _check_admins(conn: sqlite3.Connection) -> None:
    """There is deliberately NO default account: create the first admin with manage_users.py."""
    if not conn.execute("SELECT 1 FROM users WHERE is_admin = 1").fetchone():
        print("!! No admin account yet. Create one:  python manage_users.py add <name> --admin")


def init_db() -> None:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        _check_admins(conn)
