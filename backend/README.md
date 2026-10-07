# Backend

## First-time setup

A fresh install has no account. Create it and enroll your authenticator app:

```
python -m app.cli create-user --username <you>
```

With Docker:

```
docker compose exec backend python -m app.cli create-user --username <you>
```

You will be asked for a password (12+ characters) twice, then shown a QR code to
scan with your authenticator app and asked for a 6-digit code to confirm. Then log
in at `/#/login`. To replace the existing account's password and authenticator,
add `--reset`.
