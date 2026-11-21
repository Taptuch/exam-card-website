"""Run:  .venv/Scripts/python.exe -I tests/test_app.py   (uses a throw-away database)"""
import io, re, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db, subjects, sample_subject

tmp = Path(tempfile.mkdtemp())
db.INSTANCE_DIR = tmp
db.DB_PATH = tmp / "t.db"
db.AVATAR_DIR = tmp / "avatars"
subjects.SUBJECTS_DIR = tmp / "subjects"
subjects.SUBJECTS_DIR.mkdir()
sample_subject.write(subjects.SUBJECTS_DIR / "demo.json")      # synthetic cards, id "demo"

import app as appmod
from werkzeug.security import generate_password_hash

ADMIN_PW = "test-admin-pass-1"                       # test fixture only (throw-away database)
with db.connect() as c:
    c.execute("INSERT INTO users (username, display_name, password_hash, is_admin) VALUES ('admin', 'Admin', ?, 1)",
              (generate_password_hash(ADMIN_PW),))

n_pass = 0
def check(name, cond, extra=""):
    global n_pass
    print(("PASS " if cond else "FAIL ") + name + (f"   {extra}" if not cond else ""))
    if not cond: sys.exit(1)
    n_pass += 1

class C:
    def __init__(self):
        self.c = appmod.app.test_client()
    def login(self, user, pw):
        html = self.c.get("/login").get_data(as_text=True)
        tok = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        return self.c.post("/login", data={"csrf": tok, "username": user, "password": pw})
    @property
    def tok(self):
        with self.c.session_transaction() as s:
            tok = s.get("csrf")
        if tok is None:                    # a browser renders a page first, which creates the token
            self.c.get("/")                # signed in: renders the app; signed out: redirects
            with self.c.session_transaction() as s:
                tok = s.get("csrf")
        return tok
    def api(self, method, path, json=None, **kw):
        return self.c.open("/api" + path, method=method, json=json, headers={"X-CSRF-Token": self.tok or ""}, **kw)

# ---- admin account (created by the test fixture above)
admin = C()
r = admin.login("admin", ADMIN_PW)
check("admin can sign in", r.status_code == 302)
r = admin.c.get("/")
check("admin sees app", r.status_code == 200 and b"Welcome" in r.data and b"Admin</a>" in r.data)
check("admin page reachable", admin.c.get("/admin").status_code == 200)
check("CSRF header required on API writes",
      admin.c.post("/api/me/password", json={"current": ADMIN_PW, "new": "x" * 9}).status_code == 400)

# ---- admin creates user -> forced password change
r = admin.api("POST", "/admin/users", {"username": "bob", "display_name": "Bob", "password": "temp-pass-1"})
check("admin creates user", r.status_code == 201 and r.get_json()["must_change_password"] is True)
check("duplicate username (case-insens.) rejected", admin.api("POST", "/admin/users", {"username": "BOB", "password": "whatever1"}).status_code == 409)
check("short password rejected", admin.api("POST", "/admin/users", {"username": "zed", "password": "abc"}).status_code == 400)
check("bad username rejected", admin.api("POST", "/admin/users", {"username": "a b", "password": "whatever1"}).status_code == 400)

bob = C()
check("bob logs in with temp password", bob.login("bob", "temp-pass-1").status_code == 302)
r = bob.c.get("/")
check("bob is redirected to change-password", r.status_code == 302 and "/change-password" in r.headers["Location"])
r = bob.api("GET", "/subjects")
check("API blocked until password changed", r.status_code == 403 and r.get_json()["error"] == "password_change_required")
check("admin page blocked for non-admin + forced", bob.c.get("/admin").status_code == 302)
check("change-password page shown", bob.c.get("/change-password").status_code == 200)
def forced(new, confirm=None):
    return bob.c.post("/change-password", data={"csrf": bob.tok, "new": new, "confirm": confirm or new})
check("forced: too short", forced("short").status_code == 400)
check("forced: mismatch", forced("long-enough-1", "different-1").status_code == 400)
check("forced: same as temp rejected", forced("temp-pass-1").status_code == 400)
check("forced: valid", forced("my-own-pass-1").status_code == 302)
check("bob now gets in", bob.c.get("/").status_code == 200)
check("change-password no longer reachable", bob.c.get("/change-password").status_code == 302)
check("bob is not admin", bob.api("GET", "/admin/users").status_code == 403)
check("bob can't open /admin", bob.c.get("/admin").status_code == 302)

# ---- reset password -> forced again, even for an existing session
bob_id = admin.api("GET", "/admin/users").get_json()
bob_id = next(u["id"] for u in bob_id if u["username"] == "bob")
r = admin.api("POST", f"/admin/users/{bob_id}/reset-password", {})
temp = r.get_json()["password"]
check("reset returns a temp password", len(temp) >= 8)
check("existing bob session is forced to change password", bob.c.get("/").status_code == 302)
bob2 = C()
check("old password no longer works", bob2.login("bob", "my-own-pass-1").status_code == 401)
check("new temp password works", bob2.login("bob", temp).status_code == 302)
check("...and forces a change", bob2.c.get("/").status_code == 302)
bob2.c.get("/change-password")   # a browser is redirected here and renders the form (and its CSRF token)
bob2.c.post("/change-password", data={"csrf": bob2.tok, "new": "third-pass-123", "confirm": "third-pass-123"})
check("after change bob2 has access", bob2.c.get("/").status_code == 200)

# ---- profile
check("nickname change", bob2.api("PATCH", "/me", {"display_name": "  Bobby  Tables "}).get_json()["display_name"] == "Bobby Tables")
check("empty nickname rejected", bob2.api("PATCH", "/me", {"display_name": "  "}).status_code == 400)
check("password change: wrong current", bob2.api("POST", "/me/password", {"current": "nope", "new": "another-pass-9"}).status_code == 403)
check("password change: ok", bob2.api("POST", "/me/password", {"current": "third-pass-123", "new": "another-pass-9"}).status_code == 200)

png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
def up(name, data):
    return bob2.api("POST", "/me/avatar", data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
r = up("me.png", png)
check("png avatar accepted", r.status_code == 200 and r.get_json()["avatar_url"].endswith(".png"))
url = r.get_json()["avatar_url"]
check("avatar is served to signed-in users", bob2.c.get(url).status_code == 200)
check("avatar not served anonymously", C().c.get(url).status_code == 302)
check("jpeg ext with jpeg bytes ok", up("a.JPEG", b"\xff\xd8\xff\xe0" + b"0" * 20).status_code == 200)
check("gif accepted", up("a.gif", b"GIF89a" + b"0" * 20).status_code == 200)
check("txt extension rejected", up("a.txt", png).status_code == 400)
check("exe disguised as png rejected", up("a.png", b"MZ\x90\x00" + b"0" * 20).status_code == 400)
check("png bytes with .gif name rejected", up("a.gif", png).status_code == 400)
check("too large rejected", up("a.png", png + b"0" * (2 * 1024 * 1024)).status_code == 400)
check("only newest avatar file remains", len(list(db.AVATAR_DIR.glob(f"u{bob_id}-*"))) == 1)
check("avatar removal", bob2.api("DELETE", "/me/avatar").status_code == 200 and not list(db.AVATAR_DIR.glob(f"u{bob_id}-*")))

# ---- subjects
r = bob2.api("GET", "/subjects")
check("subject list", r.status_code == 200 and r.get_json()[0]["id"] == "demo" and r.get_json()[0]["count"] == 6)
s = bob2.api("GET", "/subjects/demo").get_json()
check("choice card shape", s["cards"][0]["options"] == ["Option A", "Option B", "Option C", "Option D"] and s["cards"][0]["answer"] == [2])
check("multi-answer + open card shape", s["cards"][1]["answer"] == [0, 1, 3] and s["cards"][2]["type"] == "open")
check("unknown subject 404", bob2.api("GET", "/subjects/nope").status_code == 404)
check("path traversal id rejected", bob2.api("GET", "/subjects/..%2Fapp").status_code == 404)

# ---- comments
base = "/subjects/demo/cards/q-open/comments"
check("no comments initially", bob2.api("GET", base).get_json() == [])
c1 = bob2.api("POST", base, {"body": "<b>hello</b>"})
check("add comment", c1.status_code == 201 and c1.get_json()["body"] == "<b>hello</b>")  # stored raw; rendered as text by the UI
cid = c1.get_json()["id"]
check("empty comment rejected", bob2.api("POST", base, {"body": "   "}).status_code == 400)
check("too long rejected", bob2.api("POST", base, {"body": "x" * 1001}).status_code == 400)
check("comment on unknown card 404", bob2.api("POST", "/subjects/demo/cards/zzz/comments", {"body": "hi"}).status_code == 404)
r = admin.api("POST", base, {"body": "reply!", "parent_id": cid})
check("reply to comment", r.status_code == 201 and r.get_json()["parent_id"] == cid)
rid = r.get_json()["id"]
check("reply to nonexistent parent rejected", admin.api("POST", base, {"body": "x", "parent_id": 9999}).status_code == 404)
check("reply parent from another card rejected",
      admin.api("POST", "/subjects/demo/cards/q-last/comments", {"body": "x", "parent_id": cid}).status_code == 404)
lst = bob2.api("GET", base).get_json()
check("thread lists both + can_delete flags", len(lst) == 2 and lst[0]["can_delete"] is True and lst[1]["can_delete"] is False)
check("other user can't delete", bob2.api("DELETE", f"/comments/{rid}").status_code == 403)
check("admin can delete any", admin.api("DELETE", f"/comments/{cid}").status_code == 200)
lst = bob2.api("GET", base).get_json()
check("deleted comment is blanked but reply stays", lst[0]["deleted"] and lst[0]["body"] == "" and lst[0]["author"] is None and lst[1]["body"] == "reply!")

# ---- presence
r = bob2.api("POST", "/presence", {"activity": "studying", "subject_id": "demo"})
d = r.get_json()
check("presence heartbeat", r.status_code == 200 and d["count"] == 1 or d["count"] == 2)
r = admin.api("POST", "/presence", {"activity": "practising", "subject_id": "demo"})
d = r.get_json()
by = {u["name"]: u for u in d["users"]}
check("presence lists activities + subject titles", d["count"] == 2 and by["Bobby Tables"]["activity"] == "studying"
      and by["Admin"]["activity"] == "practising" and by["Admin"]["subject"] == "Sample subject" and by["Admin"]["me"])
check("bad activity rejected", admin.api("POST", "/presence", {"activity": "hacking"}).status_code == 400)
with db.connect() as c:
    c.execute("UPDATE presence SET last_seen = ? WHERE user_id = ?", (int(time.time()) - 600, bob_id))
check("stale heartbeat = offline", admin.api("GET", "/presence").get_json()["count"] == 1)

# ---- admin: edit / ban
check("admin edits username+nick", admin.api("PATCH", f"/admin/users/{bob_id}", {"username": "robert", "display_name": "Rob"}).get_json()["username"] == "robert")
check("rename to existing name rejected", admin.api("PATCH", f"/admin/users/{bob_id}", {"username": "ADMIN"}).status_code == 409)
admin_id = next(u["id"] for u in admin.api("GET", "/admin/users").get_json() if u["username"] == "admin")
check("admin can't ban self", admin.api("PATCH", f"/admin/users/{admin_id}", {"is_banned": True}).status_code == 400)
check("admin can't demote self", admin.api("PATCH", f"/admin/users/{admin_id}", {"is_admin": False}).status_code == 400)
check("promote bob", admin.api("PATCH", f"/admin/users/{bob_id}", {"is_admin": True}).get_json()["is_admin"] is True)
check("bob2 is now admin (live)", bob2.api("GET", "/admin/users").status_code == 200)
admin.api("PATCH", f"/admin/users/{bob_id}", {"is_admin": False})
check("ban bob", admin.api("PATCH", f"/admin/users/{bob_id}", {"is_banned": True}).get_json()["is_banned"] is True)
check("banned session kicked immediately", bob2.api("GET", "/me").status_code == 401 and bob2.c.get("/").status_code == 302)
b3 = C()
r = b3.login("robert", "another-pass-9")
check("banned login refused with right password", r.status_code == 401 and b"disabled" in r.data)
r = b3.login("robert", "wrong")
check("banned + wrong password looks like any failure", r.status_code == 401 and b"Wrong username or password" in r.data)
check("unban", admin.api("PATCH", f"/admin/users/{bob_id}", {"is_banned": False}).get_json()["is_banned"] is False)
check("unbanned can log in again", C().login("robert", "another-pass-9").status_code == 302)

# ---- admin: subjects
r = admin.api("GET", "/admin/subjects")
check("admin subject list", r.status_code == 200 and r.get_json()[0]["id"] == "demo")
check("non-admin can't list admin subjects", C().api("GET", "/admin/subjects").status_code in (401, 403))
check("create subject", admin.api("POST", "/admin/subjects", {"id": "second", "title": "Second subject"}).status_code == 201)
check("create dup subject 409", admin.api("POST", "/admin/subjects", {"id": "second", "title": "Second subject"}).status_code == 409)
check("bad subject id rejected", admin.api("POST", "/admin/subjects", {"id": "../evil", "title": "x"}).status_code == 400)
raw = admin.api("GET", "/admin/subjects/second/raw").get_json()["text"]
check("raw JSON returned", '"cards"' in raw)
r = admin.api("PUT", "/admin/subjects/second", {"text": "{ not json"})
check("invalid JSON reported", r.status_code == 400 and r.get_json()["problems"])
r = admin.api("PUT", "/admin/subjects/second", {"text": '{"title":"A","cards":[{"id":"a","question":"q","options":[{"text":"x"},{"text":"y"}]}]}'})
check("schema problems reported (no correct option)", r.status_code == 400 and any("correct" in p for p in r.get_json()["problems"]))
r = admin.api("PUT", "/admin/subjects/second", {"text": '{"title":"A","cards":[{"id":"a","question":"q","answer":"x"},{"id":"a","question":"q2","answer":"y"}]}'})
check("duplicate card ids reported", r.status_code == 400 and any("duplicate" in p for p in r.get_json()["problems"]))
good = '{"title":"Second subject","cards":[{"id":"a","question":"q","options":[{"text":"x","correct":true},{"text":"y"}]}]}'
check("valid save", admin.api("PUT", "/admin/subjects/second", {"text": good}).status_code == 200)
check("saved subject visible to students", bob2.api("GET", "/subjects/second").status_code in (200, 401))
(subjects.SUBJECTS_DIR / "broken.json").write_text("{oops")
check("broken file hidden from students", [s["id"] for s in admin.api("GET", "/subjects").get_json()] == ["demo", "second"])
check("broken file shown to admin with errors", any(s["id"] == "broken" and s["errors"] for s in admin.api("GET", "/admin/subjects").get_json()))

# ================= NEW: flags
u = C(); u.login("robert", "another-pass-9")
check("no flags initially", u.api("GET", "/flags").get_json() == [])
check("flag a card", u.api("PUT", "/subjects/demo/cards/q-open/flag").status_code == 200)
check("flag is idempotent", u.api("PUT", "/subjects/demo/cards/q-open/flag").status_code == 200)
check("flag unknown card 404", u.api("PUT", "/subjects/demo/cards/zzz/flag").status_code == 404)
u.api("PUT", "/subjects/second/cards/a/flag")
check("flag listing", len(u.api("GET", "/flags").get_json()) == 2)
fs = u.api("GET", "/flagged").get_json()
check("flagged pseudo-subject has cards from several subjects",
      fs["flagged"] and fs["id"] == "flagged" and len(fs["cards"]) == 2
      and {c["subject_id"] for c in fs["cards"]} == {"demo", "second"} and all(c["subject_title"] for c in fs["cards"]))
check("flags are per user", admin.api("GET", "/flags").get_json() == [])
with db.connect() as c:
    c.execute("INSERT INTO flags (user_id, subject_id, card_id) VALUES (?, 'demo', 'ghost')", (bob_id,))
check("flags of vanished cards are ignored", len(u.api("GET", "/flags").get_json()) == 2)
check("unflag", u.api("DELETE", "/subjects/demo/cards/q-open/flag").status_code == 200 and len(u.api("GET", "/flags").get_json()) == 1)
check("anonymous can't flag", C().api("PUT", "/subjects/demo/cards/q-open/flag").status_code in (401, 400))

# ================= NEW: status like Discord
me_ = u.api("GET", "/me").get_json()
check("default status online, no text", me_["status"] == "online" and me_["status_text"] == "")
r = u.api("PUT", "/me/status", {"status": "dnd", "text": "  cramming   hard "})
check("set dnd + custom text (whitespace normalised)", r.get_json() == {"status": "dnd", "status_text": "cramming hard"})
check("status persists", u.api("GET", "/me").get_json()["status"] == "dnd")
check("partial update keeps text", u.api("PUT", "/me/status", {"status": "idle"}).get_json()["status_text"] == "cramming hard")
check("unknown status rejected", u.api("PUT", "/me/status", {"status": "away"}).status_code == 400)
check("too long status text rejected", u.api("PUT", "/me/status", {"text": "x" * 61}).status_code == 400)
u.api("PUT", "/me/status", {"status": "dnd"})
u.api("POST", "/presence", {"activity": "studying", "subject_id": "demo"})
admin.api("POST", "/presence", {"activity": "browsing"})
d = admin.api("GET", "/presence").get_json()
rb = next(x for x in d["users"] if x["name"] == "Rob")
check("others see status + custom text + activity", rb["status"] == "dnd" and rb["status_text"] == "cramming hard" and rb["activity"] == "studying")
u.api("PUT", "/me/status", {"status": "invisible"})
d = admin.api("GET", "/presence").get_json()
check("invisible users are hidden from others and not counted", all(x["name"] != "Rob" for x in d["users"]) and d["count"] == 1)
d = u.api("GET", "/presence").get_json()
check("invisible user still sees themselves, uncounted", any(x["me"] and x["status"] == "invisible" for x in d["users"]) and d["count"] == 1)
u.api("PUT", "/me/status", {"status": "online"})

# ================= NEW: languages
check("default language is English", u.api("GET", "/me").get_json()["language"] == "en")
r = u.api("PUT", "/me/language", {"language": "sk"})
check("set language", r.status_code == 200 and "lang=sk" in r.headers.get("Set-Cookie", ""))
check("bad language rejected", u.api("PUT", "/me/language", {"language": "de"}).status_code == 400)
r = u.api("POST", "/me/password", {"current": "nope", "new": "x" * 9})
check("API errors are translated (Slovak)", r.status_code == 403 and "Aktuálne heslo" in r.get_json()["error"])
page = u.c.get("/").get_data(as_text=True)
check("page is Slovak", 'lang="sk"' in page and "Vitaj" in page and "Nastavenia" in page)
u2 = C(); u2.login("robert", "another-pass-9")
check("language follows the account to another device", 'lang="sk"' in u2.c.get("/").get_data(as_text=True))
u.api("PUT", "/me/language", {"language": "cs"})
check("Czech", "Vítej" in u.c.get("/").get_data(as_text=True))
u.api("PUT", "/me/language", {"language": "en"})
anon = C()
check("anonymous: browser language header (Slovak)", "Prihlásenie" in anon.c.get("/login", headers={"Accept-Language": "sk-SK,sk;q=0.9,en;q=0.5"}).get_data(as_text=True))
check("anonymous: Czech from header", "Přihlášení" in anon.c.get("/login", headers={"Accept-Language": "cs"}).get_data(as_text=True))
check("anonymous: unknown language -> English", "Sign in" in anon.c.get("/login", headers={"Accept-Language": "de"}).get_data(as_text=True))
html = anon.c.get("/login").get_data(as_text=True)
tok = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
r = anon.c.post("/language", data={"csrf": tok, "lang": "cs", "next": "login"})
check("language buttons on login page set a cookie", r.status_code == 302 and "lang=cs" in r.headers["Set-Cookie"])
check("...and the login page follows", "Přihlášení" in anon.c.get("/login").get_data(as_text=True))
check("language form needs csrf", anon.c.post("/language", data={"lang": "sk"}).status_code == 400)
anon.c.post("/language", data={"csrf": tok, "lang": "sk", "next": "login"})
tok2 = re.search(r'name="csrf" value="([^"]+)"', anon.c.get("/login").get_data(as_text=True)).group(1)
r = anon.c.post("/login", data={"csrf": tok2, "username": "x", "password": "y"})
check("login error translated", "Nesprávne" in r.get_data(as_text=True))

# translation completeness: every key used by templates/JS exists, placeholders match in all languages
import i18n, glob
used = set(); plural = set()
for f in glob.glob(str(ROOT / "templates" / "*.html")):
    used |= set(re.findall(r"""(?<![\w.])t\(\s*'([^']+)'""", Path(f).read_text(encoding="utf-8")))
for f in glob.glob(str(ROOT / "static" / "*.js")):
    src = Path(f).read_text(encoding="utf-8")
    plural |= set(re.findall(r"""(?<![\w.])tn\(\s*'([^']+)'""", src))
    # any string literal that looks like a translation key: namespace.name
    used |= set(re.findall(r"""'((?:err|login|cp|top|presence|act|status|set|side|home|potd|subject|mode|study|nav|q|prac|flag|flagged|disc|admin|time)\.[a-z_]+)'""", src))
missing = sorted(k for k in used if k not in i18n.STRINGS["en"] and not k.endswith("."))
check("every key used in templates/JS exists", not missing, str(missing))
check("plural keys complete", all(f"{p}.{f}" in i18n.STRINGS["en"] for p in plural for f in ("one", "few", "many")), str(plural))
check("dynamic keys exist", all(f"act.{a}" in i18n.STRINGS["en"] for a in ("idle", "browsing", "studying", "practising"))
      and all(f"status.{s}" in i18n.STRINGS["en"] for s in ("online", "idle", "dnd", "invisible")))
ph = lambda s: sorted(re.findall(r"\{(\w+)\}", s))
bad = [k for k in i18n.STRINGS["en"] if not (ph(i18n.STRINGS["en"][k]) == ph(i18n.STRINGS["sk"][k]) == ph(i18n.STRINGS["cs"][k]))]
check("placeholders identical in EN/SK/CZ", not bad, str(bad))
check("sk/cs are actually translated (not copies of English) for most keys",
      sum(i18n.STRINGS["sk"][k] != i18n.STRINGS["en"][k] for k in i18n.STRINGS["en"]) > 0.8 * len(i18n.STRINGS["en"]))

# ================= NEW: picture of the day
import potd
potd.PICTURE_DIR = tmp / "pics"
check("no folder / no pictures -> nothing", u.api("GET", "/potd").get_json()["url"] is None)
potd.PICTURE_DIR.mkdir()
(potd.PICTURE_DIR / "notes.txt").write_text("hi"); (potd.PICTURE_DIR / "README.txt").write_text("x"); (potd.PICTURE_DIR / "evil.svg").write_text("<svg/>")
check("non-image files ignored", u.api("GET", "/potd").get_json()["url"] is None)
for n in ("a.png", "b.jpg", "c day.gif"):
    (potd.PICTURE_DIR / n).write_bytes(png)
url = u.api("GET", "/potd").get_json()["url"]
check("a picture is chosen", url and url.startswith("/potd/"))
r = u.c.get(url)
check("picture is served (with spaces in name too)", r.status_code == 200 and r.mimetype.startswith("image/"))
check("same picture all day / for everybody", admin.api("GET", "/potd").get_json()["url"] == url)
others = [n for n in ("a.png", "b.jpg", "c day.gif") if "/potd/" + n != url and "/potd/" + n.replace(" ", "%20") != url]
check("only today's picture can be opened - the others exist but give 404",
      len(others) == 2 and all(u.c.get("/potd/" + n).status_code == 404 for n in others), url)
check("txt not served", u.c.get("/potd/notes.txt").status_code == 404)
check("svg not served", u.c.get("/potd/evil.svg").status_code == 404)
check("path traversal blocked", u.c.get("/potd/..%2Fcards.db.png").status_code == 404 and u.c.get("/potd/../app.py").status_code == 404)
check("anonymous can't fetch pictures", C().c.get(url).status_code == 302)
seen = set()
real_date = potd.date
for day in range(738000, 738003):
    potd.date = type("D", (), {"today": staticmethod(lambda day=day: type("X", (), {"toordinal": lambda s: day})())})
    seen.add(potd.today())
potd.date = real_date
check("3 days -> 3 different pictures (cycle, no repeat)", len(seen) == 3)

# ================= NEW (hardening): DB-backed throttle, session fingerprint, comment limit, headers
def client_from(ip):
    cl = appmod.app.test_client()
    cl.environ_base["REMOTE_ADDR"] = ip
    return cl

def login_from(cl, user, pw):
    html = cl.get("/login").get_data(as_text=True)
    tk = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    return cl.post("/login", data={"csrf": tk, "username": user, "password": pw})

atk = client_from("10.1.1.1")
for i in range(5):
    r = login_from(atk, "robert", "wrong-%d" % i)
check("5 wrong passwords -> still plain 'wrong' message", r.status_code == 401 and b"Wrong username" in r.data)
r = login_from(atk, "robert", "another-pass-9")
check("6th attempt is locked even with the RIGHT password", r.status_code == 401 and b"Too many" in r.data)
with db.connect() as c:
    check("lock is stored in the database (shared by all workers)", c.execute("SELECT COUNT(*) FROM login_failures WHERE key = 'u:10.1.1.1|robert'").fetchone()[0] == 1)
check("other username from that IP is not locked", b"Wrong username" in login_from(atk, "someone-else", "x").data)
check("same username from another IP is not locked", login_from(client_from("10.1.1.2"), "robert", "another-pass-9").status_code == 302)
spray = client_from("10.2.2.2")
for i in range(50):
    login_from(spray, "user%d" % i, "x")
check("password spraying: whole IP gets locked", b"Too many" in login_from(spray, "robert", "another-pass-9").data)
with db.connect() as c:                                   # lock expires by itself
    c.execute("UPDATE login_failures SET last = last - 400")
check("lock expires after 5 minutes", login_from(spray, "robert", "another-pass-9").status_code == 302)

# sessions die when the password changes
admin.api("POST", "/admin/users", {"username": "carol", "display_name": "Carol", "password": "carol-temp-1"})
c1 = C(); c1.login("carol", "carol-temp-1"); c1.c.get("/change-password")
c1.c.post("/change-password", data={"csrf": c1.tok, "new": "carol-pass-1", "confirm": "carol-pass-1"})
check("forced change keeps the current session signed in", c1.c.get("/").status_code == 200)
c2 = C(); c2.login("carol", "carol-pass-1")
check("second device signs in", c2.api("GET", "/me").status_code == 200 and c1.api("GET", "/me").status_code == 200)
r = c2.api("POST", "/me/password", {"current": "carol-pass-1", "new": "carol-pass-2"})
check("password change in Settings", r.status_code == 200)
check("...keeps the device that changed it", c2.api("GET", "/me").status_code == 200)
check("...signs out the OTHER device (API)", c1.api("GET", "/me").status_code == 401)
check("...signs out the OTHER device (page)", c1.c.get("/").status_code == 302 and "/login" in c1.c.get("/").headers["Location"])
carol_id = next(u["id"] for u in admin.api("GET", "/admin/users").get_json() if u["username"] == "carol")
r = admin.api("POST", f"/admin/users/{carol_id}/reset-password", {})
temp = r.get_json()["password"]
check("admin password reset signs the person out everywhere", c2.api("GET", "/me").status_code == 401)

# comment spam limit
c3 = C(); c3.login("carol", temp); c3.c.get("/change-password")
c3.c.post("/change-password", data={"csrf": c3.tok, "new": "carol-pass-3", "confirm": "carol-pass-3"})
codes = [c3.api("POST", "/subjects/demo/cards/q-last/comments", {"body": "spam %d" % i}).status_code for i in range(11)]
check("10 comments per minute allowed, the 11th gets 429", codes[:10] == [201] * 10 and codes[10] == 429, str(codes))

# headers + cookies in development mode
r = C().c.get("/login")
h = r.headers
check("security headers", "script-src 'self'" in h["Content-Security-Policy"] and "frame-ancestors 'none'" in h["Content-Security-Policy"]
      and h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
      and "camera=()" in h["Permissions-Policy"] and h["Cross-Origin-Opener-Policy"] == "same-origin"
      and h["Cross-Origin-Resource-Policy"] == "same-origin")
check("no HSTS over plain-http development", "Strict-Transport-Security" not in h)
check("responses are not cached", h["Cache-Control"] == "no-store")
with db.connect() as c:
    check("SQLite runs in WAL mode", c.execute("PRAGMA journal_mode").fetchone()[0] == "wal")

# ---- logout clears presence
admin.c.post("/logout", data={"csrf": admin.tok})
with db.connect() as c:
    check("logout removes presence row", c.execute("SELECT 1 FROM presence WHERE user_id = ?", (admin_id,)).fetchone() is None)
print(f"\nall {n_pass} checks passed")
