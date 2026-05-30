# Streamload v3 — opencode Deploy Prompts

Self-contained, copy-paste prompts for an AI coding agent (opencode) running
**on the VPS** (a fresh DigitalOcean Debian 13 droplet). Run them **in order**.
Each prompt assumes nothing from the previous chat except the system state it
left behind.

Substitute the placeholders before pasting:
- `<DROPLET_PUBLIC_IP>` — the droplet's public IP
- `<GITHUB_PAT>` — a GitHub PAT with `read:packages`
- `<REPO_URL>` — `https://github.com/alfanowski/Streamload.git`
- `<TMDB_API_KEY>`, `<RESEND_API_KEY>` — real API keys

> The full manual runbook these mirror is in [`DEPLOY.md`](./DEPLOY.md).
> Prerequisite (do this yourself, not via opencode): create the DNS A record
> `api.capytal.tech -> <DROPLET_PUBLIC_IP>` and confirm
> `dig +short api.capytal.tech` returns the droplet IP before running Prompt 4.

---

## Prompt 1 — Harden the droplet and install Docker

```
You are on a fresh Debian 13 DigitalOcean droplet, running as root. Do the following and report the result of each step:

1. Run `apt update && apt upgrade -y`.
2. Create a non-root sudo user named `deploy` (use a random strong password, print it once), add it to the `sudo` group, and copy root's ~/.ssh into /home/deploy/.ssh with correct ownership so I can SSH in as `deploy`.
3. Install ufw, allow OpenSSH, 80/tcp and 443/tcp, then enable it non-interactively. Show `ufw status`.
4. Install Docker Engine and the compose plugin using the official script: `curl -fsSL https://get.docker.com | sh`.
5. Add the `deploy` user to the `docker` group.
6. Verify with `docker --version` and `docker compose version`.

Do not install anything else. Report each command's outcome.
```

---

## Prompt 2 — Log in to GHCR and clone the repo

```
Run as the `deploy` user (use `sudo -iu deploy` if you are root). Do the following:

1. Log in to GitHub Container Registry so we can pull the image:
   `echo "<GITHUB_PAT>" | docker login ghcr.io -u alfanowski --password-stdin`
   Confirm you see "Login Succeeded".
2. Create /opt/streamload owned by `deploy`:
   `sudo mkdir -p /opt/streamload && sudo chown deploy:deploy /opt/streamload`
3. Clone the deploy repo into it:
   `cd /opt/streamload && git clone <REPO_URL>`
4. Confirm /opt/streamload/Streamload contains docker-compose.yml, Caddyfile, .env.prod.example, and the deploy/ directory.

Report the contents of /opt/streamload/Streamload.
```

---

## Prompt 3 — Create `.env.prod` with generated secrets

```
Work in /opt/streamload/Streamload as the `deploy` user. Create the production env file from the template, with strong generated secrets:

1. `cp .env.prod.example .env.prod`
2. Generate two strong secrets and print them once:
   - POSTGRES_PASSWORD: `openssl rand -base64 24 | tr -d '/+='`
   - STREAMLOAD_ADMIN_PASSWORD: `openssl rand -base64 24 | tr -d '/+='`
3. Edit .env.prod so that ALL of these are consistent:
   - POSTGRES_USER=streamload
   - POSTGRES_PASSWORD=<the generated db password>
   - POSTGRES_DB=streamload
   - DATABASE_URL=postgresql+asyncpg://streamload:<the SAME db password>@db:5432/streamload
     (user, password, db name MUST match the POSTGRES_* values; host MUST be `db`)
   - TMDB_API_KEY=<TMDB_API_KEY>
   - RESEND_API_KEY=<RESEND_API_KEY>
   - EMAIL_FROM=Streamload <noreply@capytal.tech>
   - STREAMLOAD_ADMIN_USERNAME=admin
   - STREAMLOAD_ADMIN_EMAIL=admin@capytal.tech
   - STREAMLOAD_ADMIN_PASSWORD=<the generated admin password>
4. Verify .env.prod is git-ignored: `git check-ignore .env.prod` should print the path. If it does NOT, STOP and tell me.
5. Print the final .env.prod with the two passwords masked.

Do not commit anything. Report the generated passwords to me securely, once.
```

---

## Prompt 4 — Bring the stack up and verify TLS

```
Work in /opt/streamload/Streamload as the `deploy` user. Bring up the three-service stack and verify it end to end. The DNS A record for api.capytal.tech already points at this droplet.

1. `docker compose pull` (pulls postgres:16-alpine, caddy:2-alpine, and ghcr.io/alfanowski/streamload-api:latest).
2. `docker compose up -d`.
3. `docker compose ps` — confirm db is "healthy" and api + caddy are "running".
4. `docker compose logs api` — confirm "alembic upgrade head" ran, then granian started listening on 0.0.0.0:8000.
5. Wait up to ~2 minutes for Caddy to obtain a Let's Encrypt cert, then run:
   `curl -fsS https://api.capytal.tech/api/health`
   (IMPORTANT: this app mounts routes under /api — the health path is /api/health, not /health.)
   A 200 JSON response over HTTPS means success.
6. If the https curl fails: check `docker compose logs caddy` for ACME errors, confirm `dig +short api.capytal.tech` returns this droplet's IP, and confirm `ufw status` shows 80 and 443 allowed. Report what you find.

Report `docker compose ps`, the relevant api log lines, and the curl result.
```

---

## Prompt 5 — Install the nightly backup cron

```
Work in /opt/streamload/Streamload as the `deploy` user. Set up nightly Postgres backups using deploy/backup.sh.

1. Create the backup dir: `sudo mkdir -p /opt/streamload/backups && sudo chown deploy:deploy /opt/streamload/backups`.
2. Install a crontab entry for the `deploy` user that runs the backup nightly at 03:30 and logs to /opt/streamload/backups/backup.log:
   `30 3 * * * cd /opt/streamload/Streamload && /opt/streamload/Streamload/deploy/backup.sh >> /opt/streamload/backups/backup.log 2>&1`
   (append it without clobbering any existing crontab).
3. Show `crontab -l` to confirm.
4. Run the backup once now: `./deploy/backup.sh`, then `ls -lh /opt/streamload/backups`.
5. Confirm a non-empty `streamload_<timestamp>.sql.gz` file was created.

Report the crontab and the test backup result.
```
