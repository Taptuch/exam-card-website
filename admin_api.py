"""Admin-only JSON API: manage users and edit subject JSON files."""
import json
import sqlite3
import time

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import generate_password_hash

import db
import subjects
from api import ONLINE_WINDOW, error
from i18n import t
from common import (MIN_PASSWORD_LEN, USERNAME_RE, admin_required, avatar_url,
                    clean_name, iso, random_password)

bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")
bp.before_request(admin_required(lambda: None))

USER_SELECT = """
    SELECT u.id, u.username, u.display_name, u.avatar, u.is_admin, u.is_banned,
           u.must_change_password, u.created_at, p.last_seen
    FROM users u LEFT JOIN presence p ON p.user_id = u.id
"""


def user_row_json(row) -> dict:
    last_seen = row["last_seen"]
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "avatar_url": avatar_url(row["avatar"]),
        "is_admin": bool(row["is_admin"]),
        "is_banned": bool(row["is_banned"]),
        "must_change_password": bool(row["must_change_password"]),
        "created_at": iso(row["created_at"]),
        "last_seen": last_seen,
        "online": bool(last_seen and last_seen >= time.time() - ONLINE_WINDOW and not row["is_banned"]),
    }


def _log(message: str, *args) -> None:
    current_app.logger.info("admin %s: " + message, g.user["username"], *args)   # audit trail in the server log


def _get_user(conn, user_id):
    return conn.execute(USER_SELECT + " WHERE u.id = ?", (user_id,)).fetchone()


# ------------------------------------------------------------------ users
@bp.get("/users")
def list_users():
    with db.connect() as conn:
        rows = conn.execute(USER_SELECT + " ORDER BY u.username COLLATE NOCASE").fetchall()
    return jsonify([user_row_json(r) for r in rows])


@bp.post("/users")
def create_user():
    body = request.get_json(silent=True) or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return error(t("err.username"))
    name = clean_name(body.get("display_name") or username)
    if name is None:
        return error(t("err.nickname"))
    if not isinstance(password, str) or not MIN_PASSWORD_LEN <= len(password) <= 256:
        return error(t("err.password_short", n=MIN_PASSWORD_LEN))
    try:
        with db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO users (username, display_name, password_hash, is_admin, must_change_password)
                   VALUES (?, ?, ?, ?, 1)""",   # new people choose their own password at first login
                (username, name, generate_password_hash(password), int(bool(body.get("is_admin")))))
            row = _get_user(conn, cur.lastrowid)
    except sqlite3.IntegrityError:
        return error(t("err.username_taken"), 409)
    _log("created user %r", username)
    return jsonify(user_row_json(row)), 201


@bp.patch("/users/<int:user_id>")
def update_user(user_id):
    body = request.get_json(silent=True) or {}
    fields, values = [], []

    if "username" in body:
        if not isinstance(body["username"], str) or not USERNAME_RE.match(body["username"]):
            return error(t("err.username"))
        fields.append("username = ?"); values.append(body["username"])
    if "display_name" in body:
        name = clean_name(body["display_name"])
        if name is None:
            return error(t("err.nickname"))
        fields.append("display_name = ?"); values.append(name)
    for flag in ("is_admin", "is_banned"):
        if flag in body:
            if user_id == g.user["id"] and (flag == "is_banned" and body[flag] or flag == "is_admin" and not body[flag]):
                return error(t("err.self_lockout"))
            fields.append(f"{flag} = ?"); values.append(int(bool(body[flag])))
    if not fields:
        return error(t("err.nothing"))

    try:
        with db.connect() as conn:
            if _get_user(conn, user_id) is None:
                return error(t("err.no_user"), 404)
            # `fields` only ever holds fixed "column = ?" strings built above; values are bound parameters
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", (*values, user_id))  # nosec B608
            if body.get("is_banned"):
                conn.execute("DELETE FROM presence WHERE user_id = ?", (user_id,))
            row = _get_user(conn, user_id)
    except sqlite3.IntegrityError:
        return error(t("err.username_taken"), 409)
    _log("updated user id=%s fields=%s", user_id, ",".join(sorted(body)))
    return jsonify(user_row_json(row))


@bp.post("/users/<int:user_id>/reset-password")
def reset_password(user_id):
    """Sets a random temporary password. The person must replace it before doing anything else."""
    temp = random_password()
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
            (generate_password_hash(temp), user_id))
        if cur.rowcount == 0:
            return error(t("err.no_user"), 404)
    _log("reset password of user id=%s", user_id)
    return jsonify(password=temp)


# --------------------------------------------------------------- subjects
@bp.get("/subjects")
def list_subjects():
    return jsonify(subjects.list_subjects(include_invalid=True))


@bp.post("/subjects")
def create_subject():
    body = request.get_json(silent=True) or {}
    sid, title = body.get("id", ""), (body.get("title") or "").strip()
    if not isinstance(sid, str) or not subjects.ID_RE.match(sid):
        return error(t("err.subject_id"))
    if not title:
        return error(t("err.subject_title"))
    if not subjects.create(sid, title):
        return error(t("err.subject_exists"), 409)
    return jsonify(id=sid), 201


@bp.get("/subjects/<subject_id>/raw")
def raw_subject(subject_id):
    text = subjects.read_raw(subject_id)
    if text is None:
        return error(t("err.no_subject"), 404)
    return jsonify(text=text)


@bp.put("/subjects/<subject_id>")
def save_subject(subject_id):
    if subjects.read_raw(subject_id) is None:
        return error(t("err.no_subject"), 404)
    text = (request.get_json(silent=True) or {}).get("text")
    if not isinstance(text, str):
        return error(t("err.invalid_request"))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return jsonify(error=t("err.json_invalid"), problems=[f"Line {e.lineno}, column {e.colno}: {e.msg}"]), 400
    problems = subjects.validate(data)
    if problems:
        return jsonify(error=t("err.subject_problems"), problems=problems), 400
    subjects.save(subject_id, data)
    _log("saved subject %s", subject_id)
    return jsonify(ok=True)
