import logging
import os
import secrets
from datetime import timedelta

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import admin_api
import api
import db
import i18n
import potd
import security
import settings
from common import (MIN_PASSWORD_LEN, admin_required, check_csrf, csrf_token,
                    login_required, set_lang_cookie, wants_json)
from i18n import t

app = Flask(__name__)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def load_secret_key() -> str:
    """Use SECRET_KEY from the environment, else create one once and keep it
    in instance/secret_key so sessions survive restarts."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    db.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    key_file = db.INSTANCE_DIR / "secret_key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # readable by the owner only
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return key_file.read_text().strip()


app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,          # JS can't read the cookie
    SESSION_COOKIE_SAMESITE="Lax",         # basic CSRF protection for the cookie
    SESSION_COOKIE_SECURE=settings.COOKIE_SECURE,          # on in production (HTTPS only)
    # "__Host-" makes browsers refuse the cookie unless it is Secure, path=/ and not shared with subdomains
    SESSION_COOKIE_NAME="__Host-session" if settings.COOKIE_SECURE else "session",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=3 * 1024 * 1024,    # avatar upload limit is enforced separately (2 MB)
)

if settings.ALLOWED_HOSTS:
    # answer only to our own host name(s): a forged Host header is rejected with 400
    app.config["TRUSTED_HOSTS"] = settings.ALLOWED_HOSTS
if settings.TRUST_PROXY:
    # behind nginx: take the real client address / scheme from ONE proxy hop (never enable without a proxy)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.logger.setLevel(logging.INFO)

db.init_db()
app.register_blueprint(api.bp)
app.register_blueprint(admin_api.bp)
app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["t"] = t


@app.context_processor
def inject_i18n():
    lang = g.get("lang", "en")
    return {"lang": lang, "i18n_strings": i18n.STRINGS[lang], "LANGS": i18n.LANGS, "LANG_LABELS": i18n.LABELS}


def pick_language() -> str:
    """Signed-in choice > cookie > browser setting > English."""
    if g.user is not None and g.user["language"] in i18n.LANGS:
        return g.user["language"]
    cookie = request.cookies.get("lang")
    if cookie in i18n.LANGS:
        return cookie
    return request.accept_languages.best_match(i18n.LANGS, default="en")

# --------------------------------------------------------------------------
# Brute-force protection lives in security.py (database-backed)
# --------------------------------------------------------------------------
# Hash used to waste the same time when the username doesn't exist,
# so response time doesn't reveal which usernames are real.
_DUMMY_HASH = generate_password_hash("dummy-password")


# --------------------------------------------------------------------------
# Request hooks
# --------------------------------------------------------------------------
@app.before_request
def gate():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        with db.connect() as conn:
            row = conn.execute(
                """SELECT id, username, display_name, avatar, is_admin, is_banned, must_change_password,
                          language, status, status_text, password_hash
                   FROM users WHERE id = ?""", (user_id,)).fetchone()
        if (row is None or row["is_banned"]      # deleted or banned -> kicked out immediately
                or session.get("pw") != security.pw_fingerprint(row["password_hash"])):   # password changed -> old sessions die
            session.clear()
        else:
            g.user = row
    g.lang = pick_language()

    if g.user is None:
        return None

    # every state-changing API call must carry the CSRF header
    if wants_json() and request.method not in ("GET", "HEAD", "OPTIONS"):
        check_csrf()

    # a person with a temporary password may do nothing but set a new one
    if g.user["must_change_password"] and request.endpoint not in ("change_password", "logout", "set_language", "static"):
        if wants_json():
            return jsonify(error="password_change_required"), 403
        return redirect(url_for("change_password"))
    return None


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if settings.COOKIE_SECURE:                                    # i.e. production over HTTPS
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if resp.mimetype in ("text/html", "application/json"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(HTTPException)
def json_errors(e):
    if wants_json():
        return jsonify(error=e.description), e.code
    return e


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.get("/")
@login_required
def home():
    return render_template("app.html")


@app.get("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")


@app.get("/avatars/<path:filename>")
@login_required
def avatar(filename):
    resp = send_from_directory(db.AVATAR_DIR, filename)
    resp.headers["Cache-Control"] = "private, max-age=86400"   # file names are unique per upload
    return resp


@app.get("/potd/<path:filename>")
@login_required
def potd_image(filename):
    # Only TODAY's picture is served: other files in the folder can't be opened by typing their path.
    if not potd.allowed(filename) or filename != potd.today():
        abort(404)
    resp = send_from_directory(potd.PICTURE_DIR, filename)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.post("/language")
def set_language():
    """Language buttons on the sign-in pages (signed-in people use the API from the top bar)."""
    check_csrf()
    code = request.form.get("lang")
    if code not in i18n.LANGS:
        abort(400, t("err.language"))
    if g.user is not None:
        with db.connect() as conn:
            conn.execute("UPDATE users SET language = ? WHERE id = ?", (code, g.user["id"]))
    target = request.form.get("next")
    endpoint = target if target in ("login", "change_password") else "home"
    return set_lang_cookie(redirect(url_for(endpoint)), code)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("home"))

    error = None
    username = ""
    if request.method == "POST":
        check_csrf()
        username = request.form.get("username", "").strip()[:64]
        password = request.form.get("password", "")[:256]
        remember = request.form.get("remember") == "on"

        if security.is_locked(username):
            error = t("login.locked")
        else:
            with db.connect() as conn:
                row = conn.execute(
                    "SELECT id, password_hash, is_banned FROM users WHERE username = ?",
                    (username,),
                ).fetchone()
            ok = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, password)
            if row and ok:
                if row["is_banned"]:
                    # only someone who knows the password learns the account is banned
                    error = t("login.banned")
                else:
                    security.clear_failures(username)
                    session.clear()            # new session -> prevents session fixation
                    session["user_id"] = row["id"]
                    session["pw"] = security.pw_fingerprint(row["password_hash"])
                    session.permanent = remember
                    return redirect(url_for("home"))
            else:
                security.register_fail(username)
                app.logger.warning("Failed sign-in from %s", request.remote_addr)   # for fail2ban / log review
                error = t("login.wrong")   # same message either way

    return render_template("login.html", error=error, username=username), (401 if error else 200)


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Shown right after an admin created the account or reset the password."""
    if not g.user["must_change_password"]:
        return redirect(url_for("home"))    # normal password changes happen in Settings

    error = None
    if request.method == "POST":
        check_csrf()
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        with db.connect() as conn:
            old_hash = conn.execute("SELECT password_hash FROM users WHERE id = ?",
                                    (g.user["id"],)).fetchone()["password_hash"]
            if len(new) < MIN_PASSWORD_LEN or len(new) > 256:
                error = t("err.password_short", n=MIN_PASSWORD_LEN)
            elif new != confirm:
                error = t("cp.mismatch")
            elif check_password_hash(old_hash, new):
                error = t("cp.same")
            else:
                new_hash = generate_password_hash(new)
                conn.execute(
                    "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                    (new_hash, g.user["id"]))
                session["pw"] = security.pw_fingerprint(new_hash)     # keep THIS session, drop all others
                return redirect(url_for("home"))
    return render_template("change_password.html", error=error), (400 if error else 200)


@app.post("/logout")
def logout():
    check_csrf()
    if g.user is not None:
        with db.connect() as conn:
            conn.execute("DELETE FROM presence WHERE user_id = ?", (g.user["id"],))
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    # development server only - in production the app is started by gunicorn (see wsgi.py / DEPLOY.md)
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1" and not settings.PRODUCTION)
