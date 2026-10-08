import stat

import pytest
from cryptography.fernet import Fernet

from app.services.backup.crypto import (
    ENC_NAME_RE,
    MAX_ENCRYPT_BYTES,
    BackupCryptoError,
    decrypt_bytes,
    decrypt_file,
    encrypt_bytes,
    encrypt_file,
    encrypted_name,
)

KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()
DUMP = b"PGDMP\x01\x0e\x00 whole database \x00\xff" * 50


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_encrypted_name_and_pattern():
    name = encrypted_name("tracker-20261008T023000Z.dump")
    assert name == "tracker-20261008T023000Z.dump.enc"
    assert ENC_NAME_RE.match(name)
    for other in ["tracker-20261008T023000Z.dump", "notes.dump.enc", "tracker-latest.dump.enc", name + ".bak"]:
        assert not ENC_NAME_RE.match(other), other


def test_file_round_trip_is_private_and_ciphertext_hides_the_dump(tmp_path):
    src, enc, out = tmp_path / "a.dump", tmp_path / "a.dump.enc", tmp_path / "b.dump"
    src.write_bytes(DUMP)
    encrypt_file(src, enc, KEY)
    assert b"whole database" not in enc.read_bytes()
    assert _mode(enc) == 0o600
    decrypt_file(enc, out, KEY)
    assert out.read_bytes() == DUMP
    assert _mode(out) == 0o600


def test_encrypt_overwrites_an_existing_temp_file_and_tightens_its_mode(tmp_path):
    src, enc = tmp_path / "a.dump", tmp_path / "tmp.enc"
    src.write_bytes(DUMP)
    enc.write_bytes(b"stale")
    enc.chmod(0o644)
    encrypt_file(src, enc, KEY)
    assert decrypt_bytes(enc.read_bytes(), KEY) == DUMP
    assert _mode(enc) == 0o600


def test_wrong_key_fails_cleanly_and_writes_nothing(tmp_path):
    enc, out = tmp_path / "a.dump.enc", tmp_path / "b.dump"
    enc.write_bytes(encrypt_bytes(DUMP, KEY))
    with pytest.raises(BackupCryptoError) as excinfo:
        decrypt_file(enc, out, OTHER_KEY)
    assert "wrong BACKUP_ENCRYPTION_KEY" in str(excinfo.value)
    assert KEY not in str(excinfo.value) and OTHER_KEY not in str(excinfo.value)
    assert not out.exists()


def test_damaged_or_plain_file_fails_cleanly(tmp_path):
    enc, out = tmp_path / "a.dump.enc", tmp_path / "b.dump"
    enc.write_bytes(DUMP)
    with pytest.raises(BackupCryptoError, match="damaged or not an encrypted backup"):
        decrypt_file(enc, out, KEY)
    assert not out.exists()


def test_decrypt_refuses_to_overwrite(tmp_path):
    enc, out = tmp_path / "a.dump.enc", tmp_path / "b.dump"
    enc.write_bytes(encrypt_bytes(DUMP, KEY))
    out.write_bytes(b"keep me")
    with pytest.raises(BackupCryptoError, match="already exists"):
        decrypt_file(enc, out, KEY)
    assert out.read_bytes() == b"keep me"


def test_decrypt_refuses_a_dangling_symlink_as_output(tmp_path):
    enc, out = tmp_path / "a.dump.enc", tmp_path / "b.dump"
    enc.write_bytes(encrypt_bytes(DUMP, KEY))
    out.symlink_to(tmp_path / "elsewhere.dump")
    with pytest.raises(BackupCryptoError, match="already exists"):
        decrypt_file(enc, out, KEY)
    assert not (tmp_path / "elsewhere.dump").exists()


def test_missing_input_is_a_clean_error(tmp_path):
    with pytest.raises(BackupCryptoError, match="cannot read the encrypted file"):
        decrypt_file(tmp_path / "nope.enc", tmp_path / "out.dump", KEY)
    with pytest.raises(BackupCryptoError, match="cannot read the dump"):
        encrypt_file(tmp_path / "nope.dump", tmp_path / "out.enc", KEY)


@pytest.mark.parametrize("key", [None, "", "not-a-fernet-key"])
def test_missing_or_bad_key(tmp_path, key):
    src = tmp_path / "a.dump"
    src.write_bytes(DUMP)
    with pytest.raises(BackupCryptoError, match="BACKUP_ENCRYPTION_KEY"):
        encrypt_file(src, tmp_path / "a.enc", key)


def test_an_oversized_dump_is_refused_before_it_is_read(tmp_path, monkeypatch):
    src = tmp_path / "a.dump"
    src.write_bytes(b"x" * 3 * 1024 * 1024)
    monkeypatch.setattr(type(src), "read_bytes", lambda self: pytest.fail("read an oversized dump"))
    with pytest.raises(BackupCryptoError) as excinfo:
        encrypt_file(src, tmp_path / "a.enc", KEY, max_bytes=2 * 1024 * 1024)
    assert str(excinfo.value) == "the dump is 3 MB, over the 2 MB limit for the off-site copy"
    assert not (tmp_path / "a.enc").exists()


def test_default_size_cap_fits_a_small_server():
    # Fernet holds ~4x the dump in memory; 100 MB keeps that well under 1 GB.
    assert MAX_ENCRYPT_BYTES == 100 * 1024 * 1024
