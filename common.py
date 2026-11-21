"""Helpers shared by the app and its blueprints: CSRF, access decorators, small formatters."""
import re
import secrets
from functools import wraps

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from i18n import t

MIN_PASSWORD_LEN = 8
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes


def wants_json() -> bool:
    return request.path.startswith("/api/")


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf() -> None:
    """Accepts the token from a form field or from the X-CSRF-Token header (fetch calls)."""
    sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf")
    if not expected or not secrets.compare_digest(sent, expected):
        abort(400, t("err.csrf"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if wants_json():
                return jsonify(error=t("err.not_signed_in")), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if wants_json():
                return jsonify(error=t("err.not_signed_in")), 401
            return redirect(url_for("login"))
        if not g.user["is_admin"]:
            if wants_json():
                return jsonify(error=t("err.admins_only")), 403
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def set_lang_cookie(resp, code: str):
    """Remember the language for the login page and for signed-out visits."""
    resp.set_cookie("lang", code, max_age=365 * 24 * 3600, samesite="Lax", httponly=True,
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", False))
    return resp


def random_password(length: int = 10) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def avatar_url(filename: str | None) -> str | None:
    return f"/avatars/{filename}" if filename else None


def iso(sqlite_ts: str | None) -> str | None:
    """'2026-01-31 12:00:00' (UTC, from CURRENT_TIMESTAMP) -> '2026-01-31T12:00:00Z'."""
    return sqlite_ts.replace(" ", "T") + "Z" if sqlite_ts else None


def clean_name(value) -> str | None:
    """Display names: 1-30 visible characters, no control characters."""
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if not 1 <= len(value) <= 30 or any(ord(ch) < 32 for ch in value):
        return None
    return value
