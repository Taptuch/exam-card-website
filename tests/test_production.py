"""Production-mode checks. Run in its own process (settings are read from the environment once):

    .venv/Scripts/python.exe -I tests/test_production.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tmp = Path(tempfile.mkdtemp())
os.environ.update(
    APP_ENV="production", TRUST_PROXY="1", ALLOWED_HOSTS="app.example.com",
    DATA_DIR=str(tmp / "data"), SUBJECTS_DIR=str(tmp / "subjects"), PICTURE_DIR=str(tmp / "pictures"),
)
(tmp / "subjects").mkdir()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_subject
sample_subject.write(tmp / "subjects" / "demo.json")

import db, settings
from werkzeug.security import generate_password_hash

n = 0
def check(name, cond, extra=""):
    global n
    print(("PASS " if cond else "FAIL ") + name + (f"   {extra}" if not cond else ""))
    if not cond:
        sys.exit(1)
    n += 1

check("settings: production + secure cookies", settings.PRODUCTION and settings.COOKIE_SECURE and settings.TRUST_PROXY)
check("data dirs come from the environment", db.DB_PATH == (tmp / "data" / "cards.db").resolve())

import app as appmod

with db.connect() as c:
    check("fresh production DB has NO default admin", c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0)
check("secret key file was created", (tmp / "data" / "secret_key").is_file())
check("the app is not in debug mode", not appmod.app.debug)

# init_db() never creates an account on its own, however often it runs
db.init_db()
with db.connect() as c:
    check("init_db() creates no default account", c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0)
with db.connect() as c:
    c.execute("DELETE FROM users")
    c.execute("INSERT INTO users (username, display_name, password_hash, is_admin) VALUES ('boss', 'Boss', ?, 1)",
              (generate_password_hash("Str0ng-pass-123"),))


def post_login(cl, user, pw, ip=None):
    headers = {"X-Forwarded-For": ip} if ip else {}
    html = cl.get("/login", headers=headers, base_url="https://app.example.com").get_data(as_text=True)
    tok = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    return cl.post("/login", data={"csrf": tok, "username": user, "password": pw},
                   headers=headers, base_url="https://app.example.com")


cl = appmod.app.test_client()
r = post_login(cl, "admin", "admin")
check("a guessed default account (admin/admin) does not exist", r.status_code == 401)

r = appmod.app.test_client().get("/login", base_url="https://app.example.com")     # fresh visitor -> a session cookie is issued
cookie = r.headers.get("Set-Cookie", "")
check("session cookie is __Host-, Secure, HttpOnly, SameSite=Lax, Path=/",
      cookie.startswith("__Host-session=") and "Secure" in cookie and "HttpOnly" in cookie
      and "SameSite=Lax" in cookie and "Path=/" in cookie and "Domain" not in cookie, cookie)
check("HSTS header", "max-age=31536000" in r.headers.get("Strict-Transport-Security", ""))
check("a forged Host header is rejected", appmod.app.test_client().get("/login", base_url="https://evil.example").status_code == 400)
check("another allowed-host spelling (upper case + port) still works", appmod.app.test_client().get("/login", base_url="https://APP.example.com:443").status_code == 200)
check("CSP present", "default-src 'self'" in r.headers["Content-Security-Policy"])

cl2 = appmod.app.test_client()
r = post_login(cl2, "boss", "Str0ng-pass-123")
check("real admin can sign in", r.status_code == 302)
check("signed-in app works", cl2.get("/", base_url="https://app.example.com").status_code == 200)
check("language cookie is Secure too", "Secure" in cl2.post("/language", data={"csrf": re.search(r'name="csrf" value="([^"]+)"',
      cl2.get("/", base_url="https://app.example.com").get_data(as_text=True)).group(1), "lang": "sk"}, base_url="https://app.example.com").headers["Set-Cookie"])

# behind nginx every request comes from 127.0.0.1; the real address is in X-Forwarded-For
victim = appmod.app.test_client()
for i in range(5):
    post_login(victim, "boss", "bad-%d" % i, ip="203.0.113.7")
r = post_login(victim, "boss", "Str0ng-pass-123", ip="203.0.113.7")
check("attacker IP behind the proxy is locked out", r.status_code == 401 and b"Too many" in r.data)
r = post_login(appmod.app.test_client(), "boss", "Str0ng-pass-123", ip="198.51.100.20")
check("a different visitor behind the same proxy is NOT locked out", r.status_code == 302)
with db.connect() as c:
    keys = [row[0] for row in c.execute("SELECT key FROM login_failures")]
check("throttle keys use the real client IP, not the proxy's", any("203.0.113.7|boss" in k for k in keys) and not any("127.0.0.1|boss" in k for k in keys), str(keys))

spoof = appmod.app.test_client()
for i in range(5):
    post_login(spoof, "boss", "bad-%d" % i, ip="1.2.3.4, 203.0.113.99")   # client-supplied part must be ignored
with db.connect() as c:
    keys = [row[0] for row in c.execute("SELECT key FROM login_failures")]
check("a forged X-Forwarded-For prefix is ignored (only the proxy's entry counts)",
      any("203.0.113.99" in k for k in keys) and not any("1.2.3.4" in k for k in keys), str(keys))

print(f"\nall {n} production checks passed")
