import pytest

from app.services.auth_service import authenticate, login_throttle
from app.services.errors import InvalidCredentialsError, TooManyAttemptsError


def _fail(db_session, times: int) -> None:
    for _ in range(times):
        with pytest.raises(InvalidCredentialsError):
            authenticate(db_session, "dxwu", "wrong", "000000")


def test_authenticate_succeeds_with_correct_credentials(db_session, seeded_credential):
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_authenticate_rejects_wrong_password(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "wrong", seeded_credential.current_totp_code())


def test_authenticate_rejects_unknown_username(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "nobody", "correct-horse", seeded_credential.current_totp_code())


def test_authenticate_rejects_wrong_totp(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", "000000")


def test_authenticate_rejects_malformed_password_hash(db_session, seeded_credential):
    seeded_credential.row.password_hash = "not-a-bcrypt-hash"
    db_session.commit()
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_authenticate_rejects_unconfirmed_totp_even_with_correct_password(
    db_session, seeded_credential_unconfirmed
):
    """Fail closed: an account whose TOTP enrollment was never confirmed cannot log in."""
    for code in ("", seeded_credential_unconfirmed.current_totp_code()):
        with pytest.raises(InvalidCredentialsError):
            authenticate(db_session, "dxwu", "correct-horse", code)


def test_authenticate_rejects_confirmed_account_missing_secret(db_session, seeded_credential):
    seeded_credential.row.totp_secret_encrypted = None
    db_session.commit()
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", "000000")


# -- TOTP replay guard ---------------------------------------------------------


def test_successful_login_stores_the_accepted_step(db_session, seeded_credential):
    assert seeded_credential.row.last_totp_step is None
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())
    db_session.refresh(seeded_credential.row)
    assert seeded_credential.row.last_totp_step is not None


def test_same_totp_code_cannot_be_used_twice(db_session, seeded_credential):
    code = seeded_credential.current_totp_code()
    authenticate(db_session, "dxwu", "correct-horse", code)
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", code)


def test_code_from_an_older_step_than_the_stored_one_is_rejected(db_session, seeded_credential):
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.totp_code_at_offset(1))
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_a_later_step_is_accepted_after_an_earlier_one(db_session, seeded_credential):
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.totp_code_at_offset(1))


def test_replayed_code_counts_as_a_failed_attempt(db_session, seeded_credential):
    code = seeded_credential.current_totp_code()
    authenticate(db_session, "dxwu", "correct-horse", code)
    assert login_throttle.failures == 0
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", code)
    assert login_throttle.failures == 1


# -- Failed-login throttle -----------------------------------------------------


def test_first_four_failures_do_not_lock_out(db_session, seeded_credential):
    _fail(db_session, 4)
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_five_failures_lock_out_further_attempts(db_session, seeded_credential):
    _fail(db_session, 5)
    with pytest.raises(TooManyAttemptsError):
        authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_lockout_rejects_before_any_bcrypt_work(db_session, seeded_credential, monkeypatch):
    _fail(db_session, 5)

    def boom(*args, **kwargs):
        raise AssertionError("bcrypt verification ran during lockout")

    monkeypatch.setattr("app.services.auth_service.verify_password", boom)
    with pytest.raises(TooManyAttemptsError):
        authenticate(db_session, "dxwu", "correct-horse", "000000")


def test_lockout_lasts_one_second_after_fifth_failure_then_lifts(
    db_session, seeded_credential, login_throttle_clock
):
    _fail(db_session, 5)  # n=5 -> 2**0 = 1 second
    login_throttle_clock.advance(0.5)
    with pytest.raises(TooManyAttemptsError):
        authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())
    login_throttle_clock.advance(0.6)
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())


def test_backoff_doubles_with_each_further_failure(db_session, login_throttle_clock):
    _fail(db_session, 5)
    for seconds in (1, 2, 4, 8):
        assert login_throttle.blocked_until - login_throttle_clock.now == pytest.approx(seconds)
        login_throttle_clock.advance(seconds)
        _fail(db_session, 1)


def test_backoff_is_capped_at_300_seconds(db_session, login_throttle_clock):
    _fail(db_session, 5)
    for _ in range(20):
        login_throttle_clock.advance(10_000)
        _fail(db_session, 1)
    assert login_throttle.failures == 25
    assert login_throttle.blocked_until - login_throttle_clock.now == pytest.approx(300)
    login_throttle_clock.advance(299)
    with pytest.raises(TooManyAttemptsError):
        authenticate(db_session, "dxwu", "wrong", "000000")


def test_too_many_attempts_error_reports_seconds_remaining(db_session, login_throttle_clock):
    _fail(db_session, 5)
    login_throttle_clock.advance(1)
    _fail(db_session, 1)  # n=6 -> 2 seconds
    login_throttle_clock.advance(2)
    _fail(db_session, 1)  # n=7 -> 4 seconds
    login_throttle_clock.advance(1)
    with pytest.raises(TooManyAttemptsError) as excinfo:
        authenticate(db_session, "dxwu", "wrong", "000000")
    assert excinfo.value.retry_after == pytest.approx(3)


def test_rejected_attempts_during_lockout_do_not_extend_it(db_session):
    _fail(db_session, 5)
    for _ in range(3):
        with pytest.raises(TooManyAttemptsError):
            authenticate(db_session, "dxwu", "wrong", "000000")
    assert login_throttle.failures == 5


def test_success_resets_the_failure_count(db_session, seeded_credential):
    _fail(db_session, 4)
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())
    assert login_throttle.failures == 0
    _fail(db_session, 4)  # would be 8 without the reset, i.e. locked out
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.totp_code_at_offset(1))


def test_failures_are_global_across_usernames(db_session, seeded_credential):
    for name in ("a", "b", "c", "d", "e"):
        with pytest.raises(InvalidCredentialsError):
            authenticate(db_session, name, "wrong", "000000")
    with pytest.raises(TooManyAttemptsError):
        authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())
