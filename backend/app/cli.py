"""Command-line tools. Usage:
python -m app.cli create-user --username <u> [--reset]
python -m app.cli restore-check <dump>
python -m app.cli decrypt-backup <in.dump.enc> <out.dump>
python -m app.cli restore <file.dump|file.dump.enc> (--check | --yes)  (use ops/server/restore.sh)"""

import argparse
import getpass
import sys

import qrcode

from app.core.config import settings
from app.core.security import totp_provisioning_uri
from app.db.session import SessionLocal
from app.services.backup.crypto import BackupCryptoError, decrypt_file
from app.services.backup.dump import BackupError, list_dump
from app.services.backup.restore import check_backup, restore_backup
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


def _restore_check(dump: str) -> int:
    """List a dump with `pg_restore --list` to check that it is readable."""
    try:
        listing = list_dump(dump)
    except BackupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {dump} is a readable dump.")
    if listing.created_at:
        print(f"Created: {listing.created_at}")
    if listing.database_version:
        print(f"PostgreSQL version: {listing.database_version}")
    print(f"{listing.entries} entries, {len(listing.tables)} tables")
    if listing.tables:
        print("Tables: " + ", ".join(listing.tables))
    return 0


def _decrypt_backup(source: str, dest: str) -> int:
    """Decrypt an off-site copy (from Google Drive) with BACKUP_ENCRYPTION_KEY."""
    if not settings.backup_encryption_key:
        print("Error: BACKUP_ENCRYPTION_KEY is not set in .env", file=sys.stderr)
        return 1
    try:
        decrypt_file(source, dest, settings.backup_encryption_key)
    except BackupCryptoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"OK: decrypted to {dest}. Check it with: python -m app.cli restore-check {dest}")
    return 0


def _restore(path: str, check: bool, yes: bool) -> int:
    """--check: is the backup readable (decrypting a .dump.enc)? --yes: replace
    the whole database with it. ops/server/restore.sh runs both, asking first,
    taking a safety backup and stopping the app in between."""
    if not (check or yes):
        print(
            "Error: this replaces the whole database. Use ops/server/restore.sh, which asks first "
            "and takes a safety backup; or pass --check to only test the file, or --yes.",
            file=sys.stderr,
        )
        return 1
    try:
        if check:
            listing = check_backup(path, settings.backup_encryption_key)
        else:
            listing = restore_backup(path, settings.database_url, settings.backup_encryption_key)
    except (BackupError, BackupCryptoError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    created = f", made {listing.created_at}" if listing.created_at else ""
    if check:
        print(f"OK: {path} is a readable backup ({len(listing.tables)} tables{created}).")
    else:
        print(f"OK: restored {path} ({len(listing.tables)} tables{created}).")
    return 0


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
    check = sub.add_parser("restore-check", help="check that a backup dump is readable (pg_restore --list)")
    check.add_argument("dump", help="path to a .dump file")
    decrypt = sub.add_parser(
        "decrypt-backup", help="decrypt an off-site copy (.dump.enc) with BACKUP_ENCRYPTION_KEY"
    )
    decrypt.add_argument("source", help="path to a .dump.enc file")
    decrypt.add_argument("dest", help="path for the decrypted .dump (must not exist)")
    restore = sub.add_parser(
        "restore", help="replace the whole database with a backup (use ops/server/restore.sh instead)"
    )
    restore.add_argument("file", help="path to a .dump, or a .dump.enc decrypted with BACKUP_ENCRYPTION_KEY")
    mode = restore.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="only check the file can be restored")
    mode.add_argument("--yes", action="store_true", help="confirm: the current data is replaced")
    args = parser.parse_args(argv)
    if args.command == "restore-check":
        return _restore_check(args.dump)
    if args.command == "decrypt-backup":
        return _decrypt_backup(args.source, args.dest)
    if args.command == "restore":
        return _restore(args.file, args.check, args.yes)
    return _create_user(args.username, args.reset)


if __name__ == "__main__":
    sys.exit(main())
