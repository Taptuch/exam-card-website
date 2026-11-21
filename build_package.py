"""Build dist/examcards-deploy.zip - the file you upload to the server (see DEPLOY.md).

    .venv/Scripts/python.exe build_package.py

Only an explicit allow-list of files goes in, so the database, secret key, avatars, the virtualenv,
tests and your editor settings can never end up on the server by accident.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist" / "examcards-deploy.zip"

FILES = [
    "app.py", "admin_api.py", "api.py", "common.py", "db.py", "i18n.py", "potd.py", "security.py",
    "settings.py", "subjects.py", "wsgi.py", "manage_users.py", "backup_db.py",
    "requirements.txt", "DEPLOY.md",
]
FOLDERS = {                      # folder -> allowed extensions
    "templates": {".html"},
    "static": {".css", ".js"},
    "subjects": {".json", ".md"},
    "picture_of_the_day": {".txt"},          # only the README; your pictures are uploaded separately
    "deploy": {".service", ".timer", ".conf", ".example"},
}


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    names = list(FILES)
    for folder, exts in FOLDERS.items():
        names += sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / folder).rglob("*")
            if p.is_file() and p.suffix in exts and "__pycache__" not in p.parts
        )
    missing = [n for n in names if not (ROOT / n).is_file()]
    if missing:
        raise SystemExit(f"missing files: {missing}")
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.write(ROOT / n, n)
    print(f"{OUT}  ({OUT.stat().st_size / 1024:.0f} KB, {len(names)} files)")


if __name__ == "__main__":
    main()
