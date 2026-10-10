"""Encryption for the off-site copy (Phase 3 spec §4.4): Fernet with
`BACKUP_ENCRYPTION_KEY`, so Google only ever holds ciphertext.

Fernet works on whole messages in memory (the plaintext, the ciphertext and
its base64 form are all held at once, roughly 4x the dump), so dumps over
MAX_ENCRYPT_BYTES are refused rather than risk running a 1 GB server out of
memory. A personal tracker's dump is a few MB.

`tracker-<UTC time>.dump` encrypts to `tracker-<UTC time>.dump.enc`;
`python -m app.cli decrypt-backup <in.enc> <out.dump>` turns it back."""

import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.services.backup.dump import FILE_MODE, clean_detail

ENC_SUFFIX = ".enc"
# tracker-20261008T023000Z.dump.enc: the only names Drive pruning will ever delete.
ENC_NAME_RE = re.compile(r"^tracker-\d{8}T\d{6}Z\.dump\.enc$")
MAX_ENCRYPT_BYTES = 100 * 1024 * 1024
_MB = 1024 * 1024


class BackupCryptoError(Exception):
    """Encrypting or decrypting a backup failed. The message is one line,
    safe to log and to show in Settings: never the key."""


def encrypted_name(dump_name: str) -> str:
    return dump_name + ENC_SUFFIX


def _fernet(key: str | None) -> Fernet:
    if not key:
        raise BackupCryptoError("BACKUP_ENCRYPTION_KEY is not set")
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise BackupCryptoError("BACKUP_ENCRYPTION_KEY is not a valid Fernet key") from None


def _write_new(path: Path, data: bytes) -> None:
    """Write `data` to a file that must not exist yet, mode 0600."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        os.fchmod(fd, FILE_MODE)  # O_CREAT's mode is filtered by the umask
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(data)
            out.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def _oserror(action: str, exc: OSError) -> BackupCryptoError:
    return BackupCryptoError(f"cannot {action}: {clean_detail(exc.strerror or str(exc))}")


def encrypt_bytes(data: bytes, key: str | None) -> bytes:
    return _fernet(key).encrypt(data)


def decrypt_bytes(token: bytes, key: str | None) -> bytes:
    try:
        return _fernet(key).decrypt(token)
    except InvalidToken:
        raise BackupCryptoError(
            "cannot decrypt: wrong BACKUP_ENCRYPTION_KEY, or the file is damaged or not an encrypted backup"
        ) from None


def encrypt_file(src: str | Path, dest: str | Path, key: str | None, *, max_bytes: int | None = None) -> None:
    """Encrypt `src` into `dest` (created or truncated, mode 0600). Raises
    BackupCryptoError, before reading anything when the dump is too large."""
    fernet = _fernet(key)
    max_bytes = MAX_ENCRYPT_BYTES if max_bytes is None else max_bytes
    src = Path(src)
    try:
        size = src.stat().st_size
    except OSError as exc:
        raise _oserror("read the dump", exc) from None
    if size > max_bytes:
        raise BackupCryptoError(
            f"the dump is {size / _MB:.0f} MB, over the {max_bytes / _MB:.0f} MB limit for the off-site copy"
        )
    try:
        data = src.read_bytes()
    except OSError as exc:
        raise _oserror("read the dump", exc) from None
    token = fernet.encrypt(data)
    del data
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        with os.fdopen(fd, "wb") as out:
            os.fchmod(fd, FILE_MODE)
            out.write(token)
    except OSError as exc:
        raise _oserror("write the encrypted copy", exc) from None


def decrypt_file(src: str | Path, dest: str | Path, key: str | None) -> None:
    """Decrypt `src` into a new file `dest` (mode 0600). Refuses to overwrite
    an existing `dest`. Raises BackupCryptoError."""
    dest = Path(dest)
    if dest.exists() or dest.is_symlink():
        raise BackupCryptoError(f"{dest} already exists; choose a new output file")
    try:
        token = Path(src).read_bytes()
    except OSError as exc:
        raise _oserror("read the encrypted file", exc) from None
    data = decrypt_bytes(token, key)
    del token
    try:
        _write_new(dest, data)
    except FileExistsError:
        raise BackupCryptoError(f"{dest} already exists; choose a new output file") from None
    except OSError as exc:
        raise _oserror("write the decrypted dump", exc) from None
