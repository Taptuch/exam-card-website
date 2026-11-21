# Exam Cards

A small self-hosted flashcard site for exam preparation. Students study prepared questions, test
themselves like in an exam, flag the cards they are unsure about and discuss them in threaded comments.

## Features

- **Subjects as JSON files** - edit them on disk or in the admin page (see [`subjects/README.md`](subjects/README.md)).
- **Study mode** (right answers shown) and **Practise mode** (exam-style test on all cards, score at the end;
  multiple-choice is graded automatically, open questions are self-graded).
- **Flagged** category: flag cards you are not sure about and study / practise just those.
- **Comments** on every card with Reddit-style replies.
- **Accounts without public registration** - an admin creates users, bans / unbans them and resets passwords
  (a reset or a new account forces a password change at the next sign-in).
- **Profile settings**: nickname, password, profile picture (png / jpg / jpeg / gif).
- **Online bookmark** with Discord-style statuses (Online, Idle, Do Not Disturb, Invisible, custom text)
  and what each person is doing (browsing, studying, practising).
- **Languages**: English, Slovak, Czech (EN / SK / CZ switch).
- **Picture of the day** on the main page, taken from a folder of images you provide.

## Stack

Python 3.10+, Flask, SQLite, plain JavaScript (no build step, no external services).

## Quick start (development)

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt     # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # Linux / macOS

python manage_users.py add yourname --admin                      # there is no default account
python app.py                                                    # http://127.0.0.1:5000
```

Then create subjects under **Admin -> Subjects** (or drop JSON files into `subjects/`), and add users under
**Admin -> Users**. Put images for the picture of the day into `picture_of_the_day/`.

## Configuration

Everything is optional in development. In production set these environment variables
(see [`deploy/examcards.env.example`](deploy/examcards.env.example)):

| Variable | Meaning |
|---|---|
| `APP_ENV=production` | secure cookies (`__Host-` prefix), HSTS |
| `ALLOWED_HOSTS` | host names the site answers to; other `Host` headers get 400 |
| `TRUST_PROXY=1` | the app runs behind exactly one reverse proxy (nginx) |
| `DATA_DIR` / `SUBJECTS_DIR` / `PICTURE_DIR` | where runtime data lives (default: next to the code) |
| `SECRET_KEY` | session signing key (default: generated once into `DATA_DIR/secret_key`) |

## Tests

```bash
python -I tests/test_app.py          # API, security and i18n checks against a throw-away database
python -I tests/test_production.py   # production mode: cookies, HSTS, host filter, proxy IPs
```

## Deployment

[`DEPLOY.md`](DEPLOY.md) (in Slovak) is a step-by-step guide for a Debian / Ubuntu server with nginx, gunicorn,
systemd and Let's Encrypt, including backups. `python build_package.py` creates the upload package
`dist/examcards-deploy.zip` from an explicit allow-list of files.

## Project layout

```
app.py, api.py, admin_api.py   routes: pages, JSON API, admin API
db.py, security.py, settings.py, common.py, i18n.py, subjects.py, potd.py   supporting modules
manage_users.py, backup_db.py, build_package.py, wsgi.py                    command-line tools / entry point
templates/, static/            HTML templates, CSS and JavaScript
deploy/                        nginx, systemd and environment templates
tests/                         test suites (synthetic data only)
```

## License

No license has been chosen yet - add a `LICENSE` file before publishing.
