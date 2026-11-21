"""JSON API used by the web page: profile, subjects, flags, comments, presence, picture of the day."""
import time
import secrets
from urllib.parse import quote

from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import db
import potd
import security
import subjects
from common import (MIN_PASSWORD_LEN, avatar_url, clean_name, iso,
                    login_required, set_lang_cookie)
from i18n import LANGS, t

bp = Blueprint("api", __name__, url_prefix="/api")
bp.before_request(login_required(lambda: None))  # every API route needs a signed-in user

ONLINE_WINDOW = 50          # seconds without a heartbeat before someone counts as offline
ACTIVITIES = {"idle", "browsing", "studying", "practising"}   # detected automatically by the page
STATUSES = {"online", "idle", "dnd", "invisible"}             # chosen by the user, like on Discord
MAX_STATUS_TEXT = 60
MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_COMMENT_LEN = 1000
MAX_COMMENTS_PER_MINUTE = 10     # per user - stops comment spam


def user_json(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "avatar_url": avatar_url(row["avatar"]),
        "is_admin": bool(row["is_admin"]),
        "language": g.lang,
        "status": row["status"],
        "status_text": row["status_text"],
    }


def error(message: str, status: int = 400):
    return jsonify(error=message), status


# ---------------------------------------------------------------- profile
@bp.get("/me")
def me():
    return jsonify(user_json(g.user))


@bp.patch("/me")
def update_me():
    name = clean_name((request.get_json(silent=True) or {}).get("display_name"))
    if name is None:
        return error(t("err.nickname"))
    with db.connect() as conn:
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, g.user["id"]))
    return jsonify(display_name=name)


@bp.put("/me/language")
def set_language():
    code = (request.get_json(silent=True) or {}).get("language")
    if code not in LANGS:
        return error(t("err.language"))
    with db.connect() as conn:
        conn.execute("UPDATE users SET language = ? WHERE id = ?", (code, g.user["id"]))
    return set_lang_cookie(jsonify(language=code), code)


@bp.put("/me/status")
def set_status():
    body = request.get_json(silent=True) or {}
    status = body.get("status", g.user["status"])
    text = body.get("text", g.user["status_text"])
    if status not in STATUSES:
        return error(t("err.status"))
    text = " ".join(text.split()) if isinstance(text, str) else None
    if text is None or len(text) > MAX_STATUS_TEXT or any(ord(ch) < 32 for ch in text):
        return error(t("err.status_text", n=MAX_STATUS_TEXT))
    with db.connect() as conn:
        conn.execute("UPDATE users SET status = ?, status_text = ? WHERE id = ?", (status, text, g.user["id"]))
    return jsonify(status=status, status_text=text)


@bp.post("/me/password")
def change_password():
    body = request.get_json(silent=True) or {}
    current, new = body.get("current", ""), body.get("new", "")
    if not isinstance(current, str) or not isinstance(new, str):
        return error(t("err.invalid_request"))
    with db.connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        if not check_password_hash(row["password_hash"], current):
            return error(t("err.password_wrong"), 403)
        if len(new) < MIN_PASSWORD_LEN or len(new) > 256:
            return error(t("err.password_short", n=MIN_PASSWORD_LEN))
        if new == current:
            return error(t("err.password_same"))
        new_hash = generate_password_hash(new)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, g.user["id"]))
    session["pw"] = security.pw_fingerprint(new_hash)      # this session stays signed in, all others are dropped
    return jsonify(ok=True)


def _image_type(data: bytes) -> str | None:
    """Look at the file's first bytes instead of trusting its name."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def _delete_avatar_file(filename: str | None) -> None:
    if filename:
        (db.AVATAR_DIR / filename).unlink(missing_ok=True)


@bp.post("/me/avatar")
def upload_avatar():
    f = request.files.get("file")
    if f is None or not f.filename:
        return error(t("err.avatar_none"))
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in {"png", "jpg", "jpeg", "gif"}:
        return error(t("err.avatar_type"))
    data = f.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        return error(t("err.avatar_big"))
    kind = _image_type(data)
    expected = "jpg" if ext in {"jpg", "jpeg"} else ext
    if kind != expected:
        return error(t("err.avatar_invalid"))

    filename = f"u{g.user['id']}-{secrets.token_hex(6)}.{kind}"
    (db.AVATAR_DIR / filename).write_bytes(data)
    with db.connect() as conn:
        conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (filename, g.user["id"]))
    _delete_avatar_file(g.user["avatar"])
    return jsonify(avatar_url=avatar_url(filename))


@bp.delete("/me/avatar")
def remove_avatar():
    with db.connect() as conn:
        conn.execute("UPDATE users SET avatar = NULL WHERE id = ?", (g.user["id"],))
    _delete_avatar_file(g.user["avatar"])
    return jsonify(avatar_url=None)


# --------------------------------------------------------------- subjects
@bp.get("/subjects")
def list_subjects():
    return jsonify(subjects.list_subjects())


@bp.get("/subjects/<subject_id>")
def get_subject(subject_id):
    subject, _ = subjects.load(subject_id)
    if subject is None:
        return error(t("err.no_subject"), 404)
    return jsonify(subject)


@bp.get("/potd")
def picture_of_the_day():
    name = potd.today()
    return jsonify(url=f"/potd/{quote(name)}" if name else None)


# ------------------------------------------------------------------ flags
def valid_flags() -> list[dict]:
    """The user's flags, minus cards that no longer exist in the subject files."""
    with db.connect() as conn:
        rows = conn.execute("SELECT subject_id, card_id FROM flags WHERE user_id = ? ORDER BY created_at",
                            (g.user["id"],)).fetchall()
    by_subject: dict[str, list[str]] = {}
    for r in rows:
        by_subject.setdefault(r["subject_id"], []).append(r["card_id"])
    out = []
    for sid, card_ids in by_subject.items():
        subject, _ = subjects.load(sid)
        if subject is None:
            continue
        existing = {c["id"] for c in subject["cards"]}
        out += [{"subject_id": sid, "card_id": cid} for cid in card_ids if cid in existing]
    return out


@bp.get("/flags")
def list_flags():
    return jsonify(valid_flags())


@bp.put("/subjects/<subject_id>/cards/<card_id>/flag")
def add_flag(subject_id, card_id):
    if not _card_exists(subject_id, card_id):
        return error(t("err.no_card"), 404)
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO flags (user_id, subject_id, card_id) VALUES (?, ?, ?)",
                     (g.user["id"], subject_id, card_id))
    return jsonify(flagged=True)


@bp.delete("/subjects/<subject_id>/cards/<card_id>/flag")
def remove_flag(subject_id, card_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM flags WHERE user_id = ? AND subject_id = ? AND card_id = ?",
                     (g.user["id"], subject_id, card_id))
    return jsonify(flagged=False)


@bp.get("/flagged")
def flagged_subject():
    """All flagged cards of the user, shaped like a subject so Study/Practise work unchanged."""
    wanted = {(f["subject_id"], f["card_id"]) for f in valid_flags()}
    cards = []
    for s in subjects.list_subjects():
        subject, _ = subjects.load(s["id"])
        for c in subject["cards"]:
            if (s["id"], c["id"]) in wanted:
                cards.append({**c, "subject_id": s["id"], "subject_title": subject["title"]})
    return jsonify(id="flagged", flagged=True, title=t("flagged.title"),
                   description=t("flagged.desc"), cards=cards)


# --------------------------------------------------------------- comments
def _card_exists(subject_id: str, card_id: str) -> bool:
    subject, _ = subjects.load(subject_id)
    return subject is not None and any(c["id"] == card_id for c in subject["cards"])


def comment_json(row) -> dict:
    deleted = bool(row["deleted"])
    return {
        "id": row["id"],
        "parent_id": row["parent_id"],
        "body": "" if deleted else row["body"],
        "deleted": deleted,
        "created_at": iso(row["created_at"]),
        "author": None if deleted else {
            "id": row["user_id"],
            "name": row["display_name"],
            "avatar_url": avatar_url(row["avatar"]),
        },
        "can_delete": not deleted and (row["user_id"] == g.user["id"] or bool(g.user["is_admin"])),
    }


COMMENT_SELECT = """
    SELECT c.id, c.parent_id, c.body, c.deleted, c.created_at, c.user_id, u.display_name, u.avatar
    FROM comments c JOIN users u ON u.id = c.user_id
"""


@bp.get("/subjects/<subject_id>/cards/<card_id>/comments")
def get_comments(subject_id, card_id):
    if not _card_exists(subject_id, card_id):
        return error(t("err.no_card"), 404)
    with db.connect() as conn:
        rows = conn.execute(COMMENT_SELECT + " WHERE c.subject_id = ? AND c.card_id = ? ORDER BY c.id",
                            (subject_id, card_id)).fetchall()
    return jsonify([comment_json(r) for r in rows])


@bp.post("/subjects/<subject_id>/cards/<card_id>/comments")
def add_comment(subject_id, card_id):
    if not _card_exists(subject_id, card_id):
        return error(t("err.no_card"), 404)
    body = request.get_json(silent=True) or {}
    text = body.get("body")
    parent_id = body.get("parent_id")
    if not isinstance(text, str) or not text.strip():
        return error(t("err.comment_empty"))
    text = text.strip()
    if len(text) > MAX_COMMENT_LEN:
        return error(t("err.comment_long", n=MAX_COMMENT_LEN))

    with db.connect() as conn:
        recent = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE user_id = ? AND created_at >= datetime('now', '-1 minute')",
            (g.user["id"],)).fetchone()[0]
        if recent >= MAX_COMMENTS_PER_MINUTE:
            return error(t("err.rate_limit"), 429)
        if parent_id is not None:
            parent = conn.execute(
                "SELECT 1 FROM comments WHERE id = ? AND subject_id = ? AND card_id = ?",
                (parent_id, subject_id, card_id)).fetchone() if isinstance(parent_id, int) else None
            if parent is None:
                return error(t("err.reply_gone"), 404)
        cur = conn.execute(
            "INSERT INTO comments (subject_id, card_id, parent_id, user_id, body) VALUES (?, ?, ?, ?, ?)",
            (subject_id, card_id, parent_id, g.user["id"], text))
        row = conn.execute(COMMENT_SELECT + " WHERE c.id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(comment_json(row)), 201


@bp.delete("/comments/<int:comment_id>")
def delete_comment(comment_id):
    with db.connect() as conn:
        row = conn.execute("SELECT user_id FROM comments WHERE id = ?", (comment_id,)).fetchone()
        if row is None:
            return error(t("err.no_comment"), 404)
        if row["user_id"] != g.user["id"] and not g.user["is_admin"]:
            return error(t("err.delete_own"), 403)
        conn.execute("UPDATE comments SET deleted = 1 WHERE id = ?", (comment_id,))
    return jsonify(ok=True)


# --------------------------------------------------------------- presence
def online_users() -> dict:
    """Who is online. People with the 'invisible' status are hidden from everybody but themselves
    and are not counted."""
    cutoff = int(time.time()) - ONLINE_WINDOW
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT u.id, u.display_name, u.avatar, u.status, u.status_text, p.activity, p.subject_id
               FROM presence p JOIN users u ON u.id = p.user_id
               WHERE p.last_seen >= ? AND u.is_banned = 0
               ORDER BY u.display_name COLLATE NOCASE""", (cutoff,)).fetchall()
    titles = {}
    users = []
    for r in rows:
        mine = r["id"] == g.user["id"]
        if r["status"] == "invisible" and not mine:
            continue
        sid = r["subject_id"]
        if sid and sid not in titles:
            subject, _ = subjects.load(sid)
            titles[sid] = subject["title"] if subject else None
        users.append({
            "name": r["display_name"],
            "avatar_url": avatar_url(r["avatar"]),
            "status": r["status"],
            "status_text": r["status_text"],
            "activity": r["activity"],
            "subject": titles.get(sid),
            "me": mine,
        })
    return {"count": sum(1 for u in users if u["status"] != "invisible"), "users": users}


@bp.get("/presence")
def get_presence():
    return jsonify(online_users())


@bp.post("/presence")
def heartbeat():
    body = request.get_json(silent=True) or {}
    activity = body.get("activity")
    subject_id = body.get("subject_id")
    if activity not in ACTIVITIES:
        return error(t("err.activity"))
    if subject_id is not None and not (isinstance(subject_id, str) and subjects.ID_RE.match(subject_id)):
        subject_id = None
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO presence (user_id, activity, subject_id, last_seen) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 activity = excluded.activity, subject_id = excluded.subject_id,
                 last_seen = excluded.last_seen""",
            (g.user["id"], activity, subject_id, int(time.time())))
    return jsonify(online_users())
