"""Deployment settings, read once from environment variables.

Development (default): everything lives next to the code, cookies work over plain http.
Production (APP_ENV=production): secure cookies + HSTS.

  APP_ENV        production | (unset = development)
  DATA_DIR       where the database, secret key and avatars live      (default: ./instance)
  SUBJECTS_DIR   the subject JSON files                              (default: ./subjects)
  PICTURE_DIR    the pictures of the day                             (default: ./picture_of_the_day)
  TRUST_PROXY    1 = the app sits behind ONE reverse proxy (nginx) that sets X-Forwarded-For/-Proto
  ALLOWED_HOSTS  comma-separated host names the site answers to, e.g. app.example.com (others get 400)
  COOKIE_SECURE  force 1/0; default = on in production
  SECRET_KEY     session signing key; default = generated once into DATA_DIR/secret_key
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


PRODUCTION = os.environ.get("APP_ENV", "").lower() == "production"
DATA_DIR = _path("DATA_DIR", BASE_DIR / "instance")
SUBJECTS_DIR = _path("SUBJECTS_DIR", BASE_DIR / "subjects")
PICTURE_DIR = _path("PICTURE_DIR", BASE_DIR / "picture_of_the_day")
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"
ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]

_cookie_flag = os.environ.get("COOKIE_SECURE")
COOKIE_SECURE = (_cookie_flag == "1") if _cookie_flag in ("0", "1") else PRODUCTION
