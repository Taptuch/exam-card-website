"""Subjects live as plain JSON files in the `subjects/` folder.

The file name is the subject id (`my-subject.json` -> "my-subject"). See subjects/README.md
for the format. Files can be edited by hand or through the admin page.
"""
import json
import os
import re
import tempfile
from pathlib import Path

import settings

SUBJECTS_DIR = settings.SUBJECTS_DIR          # env SUBJECTS_DIR, default ./subjects
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
CARD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

TEMPLATE = {
    "title": "New subject",
    "description": "",
    "cards": [
        {
            "id": "q1",
            "type": "choice",
            "question": "Example multiple-choice question?",
            "options": [
                {"text": "The right answer", "correct": True},
                {"text": "A wrong answer"},
                {"text": "Another wrong answer"},
            ],
            "explanation": "Optional text shown together with the answer.",
        },
        {
            "id": "q2",
            "type": "open",
            "question": "Example open question?",
            "answer": "The model answer you compare yourself against.",
        },
    ],
}


def _is_text(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate(data) -> list[str]:
    """Return a list of human-readable problems (empty list = valid)."""
    if not isinstance(data, dict):
        return ["The top level must be an object { ... }."]
    errs = []
    if not _is_text(data.get("title")):
        errs.append('"title" must be a non-empty text.')
    if not isinstance(data.get("description", ""), str):
        errs.append('"description" must be text.')
    cards = data.get("cards")
    if not isinstance(cards, list):
        errs.append('"cards" must be a list [ ... ].')
        return errs

    seen = set()
    for i, c in enumerate(cards, 1):
        p = f"Card {i}: "
        if not isinstance(c, dict):
            errs.append(p + "must be an object { ... }.")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not CARD_ID_RE.match(cid):
            errs.append(p + '"id" is required: letters, digits, - or _ (max 40 characters).')
        elif cid in seen:
            errs.append(p + f'duplicate "id" {cid!r}.')
        else:
            seen.add(cid)
        if not _is_text(c.get("question")):
            errs.append(p + '"question" must be a non-empty text.')
        if "explanation" in c and not isinstance(c["explanation"], str):
            errs.append(p + '"explanation" must be text.')

        kind = c.get("type", "choice" if "options" in c else "open")
        if kind == "choice":
            opts = c.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                errs.append(p + '"options" must be a list with at least 2 options.')
            elif not all(isinstance(o, dict) and _is_text(o.get("text")) for o in opts):
                errs.append(p + 'every option must look like {"text": "...", "correct": true}.')
            elif not any(o.get("correct") is True for o in opts):
                errs.append(p + 'at least one option needs "correct": true.')
        elif kind == "open":
            if not _is_text(c.get("answer")):
                errs.append(p + '"answer" must be a non-empty text.')
        else:
            errs.append(p + '"type" must be "choice" or "open".')
    return errs


def _clean(data: dict) -> dict:
    """Shape sent to the browser. Only call on validated data."""
    cards = []
    for c in data["cards"]:
        kind = c.get("type", "choice" if "options" in c else "open")
        card = {
            "id": c["id"],
            "type": kind,
            "question": c["question"],
            "explanation": c.get("explanation", ""),
        }
        if kind == "choice":
            card["options"] = [o["text"] for o in c["options"]]
            card["answer"] = [i for i, o in enumerate(c["options"]) if o.get("correct") is True]
        else:
            card["answer"] = c["answer"]
        cards.append(card)
    return {"title": data["title"], "description": data.get("description", ""), "cards": cards}


def _path(subject_id: str) -> Path | None:
    if not isinstance(subject_id, str) or not ID_RE.match(subject_id):
        return None
    return SUBJECTS_DIR / f"{subject_id}.json"


def read_raw(subject_id: str) -> str | None:
    path = _path(subject_id)
    if path is None or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def load(subject_id: str):
    """Return (clean_subject | None, errors). None + no errors = does not exist."""
    raw = read_raw(subject_id)
    if raw is None:
        return None, []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, [f"Not valid JSON: {e}"]
    errs = validate(data)
    if errs:
        return None, errs
    clean = _clean(data)
    clean["id"] = subject_id
    return clean, []


def list_subjects(include_invalid: bool = False) -> list[dict]:
    SUBJECTS_DIR.mkdir(exist_ok=True)
    out = []
    for path in sorted(SUBJECTS_DIR.glob("*.json")):
        sid = path.stem
        if not ID_RE.match(sid):
            continue
        subject, errs = load(sid)
        if subject:
            out.append({"id": sid, "title": subject["title"],
                        "description": subject["description"], "count": len(subject["cards"])})
        elif include_invalid:
            out.append({"id": sid, "title": sid, "description": "", "count": 0, "errors": errs})
    out.sort(key=lambda s: s["title"].lower())
    return out


def save(subject_id: str, data: dict) -> None:
    """Write validated data atomically so a crash never leaves a half-written file."""
    path = _path(subject_id)
    if path is None:
        raise ValueError("Invalid subject id")
    SUBJECTS_DIR.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SUBJECTS_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def create(subject_id: str, title: str) -> bool:
    """Create a new subject from the template. False if it already exists."""
    path = _path(subject_id)
    if path is None:
        raise ValueError("Invalid subject id")
    if path.exists():
        return False
    save(subject_id, {**TEMPLATE, "title": title})
    return True
