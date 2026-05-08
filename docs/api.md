# Streamload API — Operator Notes

## Environment variables

See `.env.example`. Required:

- `DATABASE_URL` — postgres+asyncpg connection string
- `RESEND_API_KEY` — Resend API key (or empty for dry-run mode)
- `WEBAUTHN_RP_ID` — relying party ID (e.g. `streamload.<tailnet>.ts.net`)
- `WEBAUTHN_ORIGIN` — full origin URL (must match what the browser sees)

## Migrations

```bash
# Create new migration after model changes
DATABASE_URL=... venv/bin/alembic revision --autogenerate -m "your description"

# Apply
DATABASE_URL=... venv/bin/alembic upgrade head

# Rollback last
DATABASE_URL=... venv/bin/alembic downgrade -1
```

## First user setup

The first registered user becomes admin automatically. To promote another:

```sql
UPDATE users SET role = 'admin' WHERE username = '<name>';
```

## Email troubleshooting

If `RESEND_API_KEY` is empty or invalid, the email client falls back to dry-run mode and logs the email rather than sending it. Useful for local dev. The verification link still works — just retrieve the token from `email_tokens` directly:

```sql
SELECT encode(token_hash, 'hex'), purpose, expires_at FROM email_tokens
  WHERE user_id = '<uuid>' AND consumed_at IS NULL ORDER BY issued_at DESC LIMIT 1;
```

(Note: `token_hash` is the hash, not the original token — for dev you can re-issue via the `/request-password-reset` endpoint and watch the log.)
