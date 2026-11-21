"""Picture of the day: one image from the `picture_of_the_day/` folder, the same for everybody.

Drop png / jpg / jpeg / gif / webp files into the folder (or set PICTURE_DIR). The picture
changes at midnight (server time) and cycles through all files before repeating one.
"""
import random
from datetime import date
from pathlib import Path

import settings

PICTURE_DIR = settings.PICTURE_DIR
EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}   # no SVG: it can carry scripts


def allowed(name: str) -> bool:
    return Path(name).suffix.lower() in EXTENSIONS


def pictures() -> list[str]:
    if not PICTURE_DIR.is_dir():
        return []
    return sorted(p.name for p in PICTURE_DIR.iterdir() if p.is_file() and allowed(p.name))


def today() -> str | None:
    files = pictures()
    if not files:
        return None
    random.Random(len(files)).shuffle(files)     # fixed shuffle: looks random, never repeats within a cycle
    return files[date.today().toordinal() % len(files)]
