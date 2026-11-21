"""Sign-in protection: brute-force throttling (stored in the database, so it holds with several
worker processes) and the fingerprint that ties a session to the password it was created with."""
import hashlib
import time

from flask import request

import db

MAX_FAILS_PER_USER = 5      # wrong passwords for one username from one IP address ...
MAX_FAILS_PER_IP = 50       # ... or for any usernames from one IP address (password spraying; high because
                            #     a school / dorm network can share one IP between many students)
LOCK_SECONDS = 5 * 60       # ... lock sign-in for this long (the counter also restarts after it)


def _keys(username: str) -> list[tuple[str, int]]:
    ip = request.remote_addr or "?"
    return [(f"u:{ip}|{username.lower()[:64]}", MAX_FAILS_PER_USER), (f"ip:{ip}", MAX_FAILS_PER_IP)]


def is_locked(username: str) -> bool:
    now = int(time.time())
    with db.connect() as conn:
        for key, limit in _keys(username):
            row = conn.execute("SELECT count, last FROM login_failures WHERE key = ?", (key,)).fetchone()
            if row and row["count"] >= limit and now - row["last"] < LOCK_SECONDS:
                return True
    return False


def register_fail(username: str) -> None:
    now = int(time.time())
    with db.connect() as conn:
        for key, _limit in _keys(username):
            conn.execute(
                """INSERT INTO login_failures (key, count, last) VALUES (?, 1, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     count = CASE WHEN ? - last >= ? THEN 1 ELSE count + 1 END,
                     last = ?""",
                (key, now, now, LOCK_SECONDS, now))
        conn.execute("DELETE FROM login_failures WHERE last < ?", (now - 3600,))   # tidy up old rows


def clear_failures(username: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM login_failures WHERE key = ?", (_keys(username)[0][0],))


def pw_fingerprint(password_hash: str) -> str:
    """Stored in the session at sign-in. When the password changes (by the user or by an admin
    reset) the fingerprint changes and every older session stops working."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:24]
