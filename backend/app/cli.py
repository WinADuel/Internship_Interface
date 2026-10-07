"""Command-line tools. Usage: python -m app.cli create-user --username <u> [--reset]"""

import argparse
import getpass
import sys

import qrcode

from app.core.security import totp_provisioning_uri
from app.db.session import SessionLocal
from app.services.user_bootstrap import (
    AccountExistsError,
    confirm_enrollment,
    create_or_reset_user,
)

MAX_CODE_ATTEMPTS = 3


def _create_user(username: str, reset: bool) -> int:
    password = getpass.getpass("Password: ")
    if getpass.getpass("Confirm password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        try:
            credential, secret = create_or_reset_user(db, username, password, reset=reset)
        except (ValueError, AccountExistsError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            db.rollback()
            return 1

        uri = totp_provisioning_uri(secret, username)
        print("Add this account to your authenticator app (scan the QR code or use the URI):")
        print(uri)
        qr = qrcode.QRCode()
        qr.add_data(uri)
        qr.make()
        qr.print_ascii(invert=True)

        for _ in range(MAX_CODE_ATTEMPTS):
            code = input("Enter the 6-digit code from your authenticator app: ").strip()
            if confirm_enrollment(db, credential, secret, code):
                db.commit()
                print("Account ready. Log in at /#/login.")
                return 0
            print("That code was not valid.", file=sys.stderr)

        db.rollback()
        print("Too many failed attempts; no account was changed.", file=sys.stderr)
        return 1
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create the account and enroll an authenticator")
    create.add_argument("--username", required=True)
    create.add_argument(
        "--reset",
        action="store_true",
        help="replace the existing account's username, password and authenticator",
    )
    args = parser.parse_args(argv)
    return _create_user(args.username, args.reset)


if __name__ == "__main__":
    sys.exit(main())
