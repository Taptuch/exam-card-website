"""Create users and reset passwords (there is no public registration page).

    python manage_users.py add <username> [--name "Display Name"] [--admin]
    python manage_users.py passwd <username>
    python manage_users.py list
"""
import argparse
import getpass
import sqlite3
import sys

from werkzeug.security import generate_password_hash

import db

MIN_PASSWORD_LEN = 8


def ask_password() -> str:
    while True:
        pw = getpass.getpass("Password: ")
        if len(pw) < MIN_PASSWORD_LEN:
            print(f"Use at least {MIN_PASSWORD_LEN} characters.")
            continue
        if pw != getpass.getpass("Repeat password: "):
            print("Passwords don't match.")
            continue
        return pw


def cmd_add(args) -> None:
    pw = ask_password()
    try:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO users (username, display_name, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                (args.username, args.name or args.username, generate_password_hash(pw), int(args.admin)),
            )
    except sqlite3.IntegrityError:
        sys.exit(f"User '{args.username}' already exists.")
    print(f"User '{args.username}' created.")


def cmd_passwd(args) -> None:
    pw = ask_password()
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (generate_password_hash(pw), args.username),
        )
    if cur.rowcount == 0:
        sys.exit(f"No such user: {args.username}")
    print("Password updated.")


def cmd_list(_args) -> None:
    with db.connect() as conn:
        for row in conn.execute("SELECT id, username, display_name, created_at FROM users"):
            print(f"{row['id']:>3}  {row['username']:<20} {row['display_name']:<25} {row['created_at']}")


def main() -> None:
    db.init_db()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="create a user")
    p.add_argument("username")
    p.add_argument("--name", help="display name (defaults to username)")
    p.add_argument("--admin", action="store_true", help="make this user an administrator")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("passwd", help="change a user's password")
    p.add_argument("username")
    p.set_defaults(func=cmd_passwd)

    p = sub.add_parser("list", help="list users")
    p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
