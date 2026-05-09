# Streamload Production Deployment — First-time Setup

## Architecture

Two GitHub repos, one server (Acer Ubuntu):

| Repo | Image | Role |
|------|-------|------|
| `alfanowski/Streamload` | `ghcr.io/alfanowski/streamload` | FastAPI backend (port 8000, internal) |
| `alfanowski/Streamload-Web` | `ghcr.io/alfanowski/streamload-web` | SvelteKit SPA via nginx (port 80, internal) |

Caddy (port 80 on host) reverse-proxies:
- `/api/*` → `streamload-api:8000`
- `/stream/*` → `streamload-api:8000`
- `/*` → `streamload-web:80`

Watchtower polls GHCR every 5 min and auto-updates `streamload-api` and `streamload-web`.

---

## Prerequisites on the Acer

- Ubuntu Server 24.04 LTS (x86_64)
- Docker + docker compose plugin installed
- Tailscale installed and authenticated, MagicDNS enabled
- Hostname set: `tailscale up --hostname=streamload`

---

## Bootstrap

```bash
# SSH to the Acer (via Tailscale)
ssh you@streamload.YOUR-TAILNET.ts.net

# Create app dir
sudo mkdir -p /opt/streamload && sudo chown $USER /opt/streamload && cd /opt/streamload

# Clone (for compose file + config templates; runtime images come from GHCR)
git clone --depth=1 https://github.com/alfanowski/Streamload.git . --branch main

# Configure
cp .env.example .env
nano .env
# Required:
#   POSTGRES_PASSWORD=$(openssl rand -hex 32)
#   RESEND_API_KEY=<your real Resend key>
#   TMDB_API_KEY=<your real TMDB v3 key>
#   WEBAUTHN_RP_ID=streamload.YOUR-TAILNET.ts.net
#   WEBAUTHN_ORIGIN=https://streamload.YOUR-TAILNET.ts.net
#   BIND_HOST=$(tailscale ip -4)
# Optional:
#   STREAMLOAD_VERSION=v0.2.0
#   STREAMLOAD_WEB_VERSION=v0.2.0

# Copy your config.json (transfer from dev machine)
scp devmachine:/path/to/Streamload/config.json .

# Restore the signing key from offline backup (USB / password manager)
mkdir -p secret
# Copy domains_signing_key.pem into secret/, then:
chmod 600 secret/domains_signing_key.pem

# Authenticate to GHCR so Watchtower can pull private images (if repo is private)
echo $GITHUB_PAT | docker login ghcr.io -u alfanowski --password-stdin

# Pull and start all services
docker compose pull
docker compose up -d

# Verify
docker compose ps
# Expected: all 5 services Up/healthy (api, web, postgres, caddy, watchtower)

docker compose logs -f streamload-api
# Wait for: "[entrypoint] Starting Streamload API server..."

# Health check through Caddy
curl -i http://$(tailscale ip -4)/api/health
# Expected: 200 OK {"status":"ok",...}

# First user registration (first registered user becomes admin)
curl -X POST http://$(tailscale ip -4)/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alfanowski","email":"you@x.com","password":"strong-password-here"}'

# Trigger initial catalog refresh (admin-only)
# First log in to get a session cookie:
curl -c /tmp/cookies.txt -X POST http://$(tailscale ip -4)/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@x.com","password":"strong-password-here"}'
curl -b /tmp/cookies.txt -X POST http://$(tailscale ip -4)/api/admin/catalog/refresh/trending-day
```

---

## Browse from your devices

Visit `http://streamload.YOUR-TAILNET.ts.net` from any device on your tailnet.

For HTTPS, use Tailscale HTTPS certificates (automatic with MagicDNS):

```bash
# On the Acer, update Caddyfile to use the MagicDNS hostname:
# Replace ":80 {" with "streamload.YOUR-TAILNET.ts.net {" and
# add: tls { ... } block if needed. Caddy will auto-provision certs.
```

To expose externally via Tailscale Funnel (optional, understand legal implications from §11):

```bash
tailscale funnel 80
```

---

## Day-to-day operations

```bash
# View logs
docker compose logs -f streamload-api
docker compose logs -f streamload-web

# Force update to latest
docker compose pull && docker compose up -d

# Pin to a specific version
STREAMLOAD_VERSION=v0.2.0 STREAMLOAD_WEB_VERSION=v0.2.0 docker compose up -d

# Rollback backend
STREAMLOAD_VERSION=v0.1.9 docker compose up -d streamload-api

# Backup database manually
docker exec streamload-postgres pg_dump -U streamload streamload | \
    gzip > /opt/streamload/data/backup-$(date +%Y-%m-%d).sql.gz

# Restore database
gunzip -c backup-YYYY-MM-DD.sql.gz | \
    docker exec -i streamload-postgres psql -U streamload streamload
```

---

## Watchtower behavior

Watchtower polls GHCR every 5 minutes. When a new `:latest` digest is detected on either `streamload-api` or `streamload-web`:

1. `docker pull` (download while old container still serves traffic)
2. `docker stop <container>` (SIGTERM, 10s grace)
3. `docker run` with new image
4. Healthcheck waits up to 60s for readiness

Total downtime per service update: 5–15s. HLS streams reconnect via player retry.

### Disabling auto-update temporarily

Pin a version in `.env`:

```bash
echo "STREAMLOAD_VERSION=v0.2.0" >> .env
echo "STREAMLOAD_WEB_VERSION=v0.2.0" >> .env
docker compose up -d streamload-api streamload-web
```

Watchtower will pull the pinned tag instead of `:latest`.

---

## Backup automation (systemd timer)

Install these files on the Acer to run daily backups at 04:00:

```ini
# /etc/systemd/system/streamload-backup.service
[Unit]
Description=Streamload Postgres backup
After=docker.service

[Service]
Type=oneshot
User=streamload
ExecStart=/opt/streamload/scripts/backup-postgres.sh
```

```ini
# /etc/systemd/system/streamload-backup.timer
[Unit]
Description=Daily Streamload backup at 04:00

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now streamload-backup.timer
sudo systemctl list-timers | grep streamload
```

---

## Resource expectations (Acer baseline)

| Service | RAM idle | CPU idle | CPU during stream |
|---------|----------|----------|-------------------|
| streamload-api | ~300 MB | <5% | 20–50% |
| streamload-web (nginx) | ~20 MB | <1% | <1% |
| postgres | <200 MB | <2% | <5% |
| caddy | ~30 MB | <1% | <1% |

Update these numbers after first real-world usage test.
