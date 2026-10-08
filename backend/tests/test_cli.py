import pyotp
import pytest
from sqlalchemy import func, select

from app import cli
from app.core.security import decrypt_value, verify_password
from app.models.auth_credential import AuthCredential
from app.services.backup.dump import BackupError, DumpListing
from app.services.user_bootstrap import create_or_reset_user

PASSWORD = "correct-horse-battery"
OLD_PASSWORD = "old-password-12345"


class _SessionProxy:
    """Delegates to the savepoint-isolated test session but ignores close(),
    which would otherwise release the connection the fixture still owns."""

    def __init__(self, session):
        self._session = session

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.fixture()
def cli_env(db_session, monkeypatch):
    monkeypatch.setattr(cli, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(cli, "qrcode", type("Q", (), {"QRCode": lambda: _FakeQR()}))
    return db_session


class _FakeQR:
    def add_data(self, data):
        pass

    def make(self):
        pass

    def print_ascii(self, **kwargs):
        pass


def _passwords(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(it))


def _codes(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def _count(db):
    return db.scalar(select(func.count()).select_from(AuthCredential))


def test_password_mismatch_writes_nothing(cli_env, monkeypatch):
    _passwords(monkeypatch, PASSWORD, "different-password")
    assert cli.main(["create-user", "--username", "me"]) != 0
    assert _count(cli_env) == 0


def test_three_wrong_codes_leaves_no_new_account(cli_env, monkeypatch):
    _passwords(monkeypatch, PASSWORD, PASSWORD)
    _codes(monkeypatch, "000000x", "abcdef", "")
    assert cli.main(["create-user", "--username", "me"]) != 0
    assert _count(cli_env) == 0


def test_reset_with_wrong_codes_keeps_old_account(cli_env, monkeypatch):
    cred, secret = create_or_reset_user(cli_env, "me", OLD_PASSWORD, reset=False)
    cred.totp_confirmed = True
    cli_env.commit()
    old_secret_blob = cred.totp_secret_encrypted

    _passwords(monkeypatch, PASSWORD, PASSWORD)
    _codes(monkeypatch, "x", "y", "z")
    assert cli.main(["create-user", "--username", "me", "--reset"]) != 0

    rows = cli_env.scalars(select(AuthCredential)).all()
    assert len(rows) == 1
    cli_env.refresh(rows[0])
    assert verify_password(OLD_PASSWORD, rows[0].password_hash)
    assert not verify_password(PASSWORD, rows[0].password_hash)
    assert rows[0].totp_confirmed is True
    assert rows[0].totp_secret_encrypted == old_secret_blob


def test_correct_code_confirms_account(cli_env, monkeypatch):
    _passwords(monkeypatch, PASSWORD, PASSWORD)
    captured = {}
    real = cli.create_or_reset_user

    def spy(*args, **kwargs):
        cred, secret = real(*args, **kwargs)
        captured["secret"] = secret
        return cred, secret

    monkeypatch.setattr(cli, "create_or_reset_user", spy)
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": pyotp.TOTP(captured["secret"]).now()
    )
    assert cli.main(["create-user", "--username", "me"]) == 0
    row = cli_env.scalars(select(AuthCredential)).one()
    assert row.totp_confirmed is True
    assert decrypt_value(row.totp_secret_encrypted) == captured["secret"]


def test_restore_check_prints_a_summary(monkeypatch, capsys):
    seen = []

    def fake_list_dump(path):
        seen.append(path)
        return DumpListing(42, ["public.applications", "public.contacts"], "16.4", "2026-10-08 02:30:05 UTC")

    monkeypatch.setattr(cli, "list_dump", fake_list_dump)
    assert cli.main(["restore-check", "/backups/nightly/tracker-20261008T023005Z.dump"]) == 0
    out = capsys.readouterr().out
    assert seen == ["/backups/nightly/tracker-20261008T023005Z.dump"]
    assert "readable dump" in out
    assert "42 entries, 2 tables" in out
    assert "public.applications, public.contacts" in out
    assert "16.4" in out


def test_restore_check_fails_on_an_unreadable_file(monkeypatch, capsys):
    def fake_list_dump(path):
        raise BackupError("not a readable dump: pg_restore: error: input file is too short")

    monkeypatch.setattr(cli, "list_dump", fake_list_dump)
    assert cli.main(["restore-check", "broken.dump"]) == 1
    assert "not a readable dump" in capsys.readouterr().err
