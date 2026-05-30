# Streamload v3 — Production Deployment Runbook

End-to-end runbook for deploying the Streamload v3 **backend** to a fresh
**DigitalOcean Debian 13** droplet (1 vCPU / 2 GB RAM / 70 GB disk).

The stack is three Docker containers managed by `docker compose`:

| Service | Image | Role |
|---------|-------|------|
| `db`    | `postgres:16-alpine` | Postgres, internal-only, named volume `pgdata` |
| `api`   | `ghcr.io/alfanowski/streamload-api:latest` | the FastAPI backend (granian) |
| `caddy` | `caddy:2-alpine` | reverse proxy + automatic HTTPS for `api.streamload.capytal.tech` |

The image is built and pushed to GHCR by GitHub Actions on every push to `main`
(`.github/workflows/deploy.yml`). The VPS **pulls** the image — it never builds.

Domain: **`api.streamload.capytal.tech`** (subdomain of `capytal.tech`, DNS controlled by
the operator).

> The client web frontend is a SEPARATE deploy and is intentionally NOT part of
> this stack. The Caddyfile has a commented block showing how to co-host it later.

> To drive this with an AI agent on the VPS, the same steps are packaged as
> copy-paste prompts in [`OPENCODE_PROMPTS.md`](./OPENCODE_PROMPTS.md).

---

## 0. Prerequisites

- A DigitalOcean droplet running **Debian 13**, public IP known.
- SSH access to the droplet as `root` (or a sudo user).
- Control of DNS for `capytal.tech`.
- A GitHub **Personal Access Token (classic)** with the `read:packages` scope
  (GitHub → Settings → Developer settings → Personal access tokens), to pull the
  GHCR image. If the GHCR package is made **public**, no token is needed to pull.

---

## 1. DNS

In your DNS provider for `capytal.tech`, add an **A record**:

```
api.streamload.capytal.tech   A   <DROPLET_PUBLIC_IP>   (TTL 300)
```

Wait for propagation before bringing up Caddy — Let's Encrypt validation fails if
`api.streamload.capytal.tech` doesn't resolve to this droplet yet. Check:

```bash
dig +short api.streamload.capytal.tech    # must print the droplet IP
```

Propagation is usually minutes, occasionally up to an hour.

---

## 2. Provision the droplet (harden + Docker)

SSH in as root, then:

```bash
# --- update base system ---
apt update && apt upgrade -y

# --- non-root sudo user (replace 'deploy' if you like) ---
adduser deploy            # set a password when prompted
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy/   # copy your SSH key

# --- firewall: SSH + HTTP + HTTPS only ---
apt install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status

# --- Docker Engine + compose plugin (official convenience script) ---
curl -fsSL https://get.docker.com | sh

# --- let 'deploy' run docker without sudo ---
usermod -aG docker deploy
```

Log out and back in **as `deploy`** (so the docker group applies):

```bash
ssh deploy@<DROPLET_PUBLIC_IP>
docker --version
docker compose version
```

---

## 3. Authenticate to GHCR (pull access)

As the `deploy` user, log in with your GitHub username and the PAT
(`read:packages`):

```bash
echo "<YOUR_GITHUB_PAT>" | docker login ghcr.io -u alfanowski --password-stdin
```

Expect `Login Succeeded`. (Skip entirely if the GHCR package is public.)

---

## 4. Get the deploy files onto the VPS

Clone the repo so the compose file, Caddyfile, and deploy scripts are present.
We use `/opt/streamload` as the home for everything.

```bash
sudo mkdir -p /opt/streamload
sudo chown deploy:deploy /opt/streamload
cd /opt/streamload
git clone https://github.com/alfanowski/Streamload.git
cd /opt/streamload/Streamload
```

> Only the compose/Caddyfile/scripts are used from the clone — the application
> code runs from the pre-built GHCR image, not this checkout.

---

## 5. Create `.env.prod` with real secrets

```bash
cp .env.prod.example .env.prod

# generate strong secrets:
echo "POSTGRES_PASSWORD: $(openssl rand -base64 24 | tr -d '/+=')"
echo "ADMIN_PASSWORD:    $(openssl rand -base64 24 | tr -d '/+=')"
```

Edit `.env.prod` and set, **consistently**:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `DATABASE_URL` — reuse the **same** user/password/db, host `db`:
  `postgresql+asyncpg://<USER>:<PASSWORD>@db:5432/<DB>`
- `TMDB_API_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`
- `STREAMLOAD_ADMIN_USERNAME`, `STREAMLOAD_ADMIN_EMAIL`, `STREAMLOAD_ADMIN_PASSWORD`

> `.env.prod` is git-ignored and must NEVER be committed. Only
> `.env.prod.example` is tracked.

Quick consistency check:

```bash
grep -E '^(POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB|DATABASE_URL)=' .env.prod
```

---

## 6. Bring the stack up

```bash
cd /opt/streamload/Streamload
docker compose pull          # pulls postgres, caddy, and the GHCR api image
docker compose up -d
```

On first boot the `api` container's entrypoint:
1. runs `alembic upgrade head` (creates the schema in the empty DB), then
2. starts granian; the app's lifespan then provisions the admin user from
   `STREAMLOAD_ADMIN_*` and starts the background catalog-refresh worker.

The DB starts **empty** apart from the schema. Catalog items populate on demand
(lazy ingest) and via the background worker (needs `TMDB_API_KEY`). There is no
seed step.

---

## 7. Verify

```bash
docker compose ps                 # 3 services up, db healthy
docker compose logs -f api        # look for "alembic upgrade head" then granian

# TLS + app reachable from the internet (Caddy will have issued a cert).
# NOTE: this app mounts everything under /api — health is /api/health and the
# OpenAPI schema is /api/openapi.json (NOT /openapi.json).
curl -fsS https://api.streamload.capytal.tech/api/health; echo
```

A `200` `{"status":"ok",...}` over **https** confirms: image pulled, migrations
applied, granian serving, Caddy proxying, and TLS issued.

### First admin login check

```bash
curl -i -X POST https://api.streamload.capytal.tech/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<STREAMLOAD_ADMIN_USERNAME>","password":"<STREAMLOAD_ADMIN_PASSWORD>"}'
```

A `2xx` with `Set-Cookie: ...; Secure` confirms cookies are secure (because
traffic is HTTPS via Caddy).

> If login expects `email` instead of `username`, check
> `streamload/api/routes/auth.py` for the exact request schema.

---

## 8. Install the nightly backup cron

`deploy/backup.sh` dumps the DB via `docker compose exec` to
`/opt/streamload/backups`, gzipped and timestamped, keeping the last 14.

```bash
sudo mkdir -p /opt/streamload/backups
sudo chown deploy:deploy /opt/streamload/backups

# nightly at 03:30 (append without clobbering existing crontab):
( crontab -l 2>/dev/null; \
  echo "30 3 * * * cd /opt/streamload/Streamload && /opt/streamload/Streamload/deploy/backup.sh >> /opt/streamload/backups/backup.log 2>&1" \
) | crontab -

crontab -l                 # verify
./deploy/backup.sh         # test once now
ls -lh /opt/streamload/backups
```

### Restore from a backup (reference)

```bash
gunzip -c /opt/streamload/backups/streamload_YYYYMMDD_HHMMSS.sql.gz \
  | docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB>
```

---

## 9. Updating (deploy a new version)

CI builds + pushes a new `:latest` (and `:sha-<...>`) image to GHCR on every push
to `main`. To deploy it:

```bash
cd /opt/streamload/Streamload
git pull                 # refresh compose/Caddyfile/scripts if they changed
docker compose pull      # fetch the new :latest api image
docker compose up -d     # recreate changed containers (migrations run on api boot)
docker image prune -f    # optional: reclaim space
```

---

## 10. Rollback

Every build is also tagged `:sha-<full_commit_sha>`. The compose `api` service
honours an `API_TAG` env var (`...:${API_TAG:-latest}`), so to roll back:

```bash
cd /opt/streamload/Streamload
# pin a previous image for this up:
API_TAG=sha-<previous_full_sha> docker compose up -d api
```

To make it sticky, add `API_TAG=sha-<...>` to `.env.prod` and `docker compose
up -d`. Remove it (or set back to `latest`) once the issue is fixed.

> A code rollback does NOT roll back applied migrations. If a release added a
> migration, downgrading may require
> `docker compose exec api alembic downgrade <rev>` — check the migration before
> rolling back across a schema change.

---

## 11. Troubleshooting

### TLS certificate not issued / `curl` fails on https  ← MOST LIKELY FIRST-DEPLOY ISSUE
- **Top cause:** DNS for `api.streamload.capytal.tech` isn't pointing at the droplet yet, or
  hasn't propagated. `dig +short api.streamload.capytal.tech` MUST return the droplet IP.
  Let's Encrypt validates over HTTP-01 on port 80.
- Ensure ports **80 and 443** are open in `ufw` (`ufw status`) AND not blocked by
  a DigitalOcean cloud firewall.
- Check Caddy logs: `docker compose logs caddy` (look for ACME errors).
- Caddy retries automatically; once DNS/ports are correct the cert issues within
  a minute or two.

### `api` container restarts / "DB connection refused"
- The `api` service waits for `db` to be `service_healthy`, but a wrong
  `DATABASE_URL` still fails. Confirm host `db`, port `5432`, and that
  user/password/db match `POSTGRES_*`. Check `docker compose logs db`.
- `docker compose ps` should show `db` as `healthy`.

### Migration failures on boot (`alembic upgrade head` errors)
- Read `docker compose logs api` — the entrypoint prints the alembic step.
- Alembic reuses `DATABASE_URL` (asyncpg) with an async engine, unchanged. A
  driver/connection error almost always means a wrong URL (host/creds), not the
  driver.
- Inspect: `docker compose exec api alembic current` / `... alembic history`.

### Healthcheck shows `unhealthy` but app seems fine
- The HEALTHCHECK curls `http://127.0.0.1:8000/api/health` (not `/health`). If
  you changed the route prefix, update the Dockerfile HEALTHCHECK and Caddy.
