# Streamload v2 — Plan 6: Containerization + CI/CD + Production Deployment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Productionize Streamload v2: a multi-stage Dockerfile (~250 MB), `docker-compose.yml` orchestrating Streamload + Postgres + Watchtower, GitHub Actions pipeline that builds and pushes multi-arch images to GHCR on every main push, semver tags trigger Releases, and Watchtower polls every 5 min to auto-deploy. End state: first-time Acer bootstrap brings the full stack up; subsequent updates deploy automatically within ~10 min of `git push`.

**Architecture:** Three-stage Dockerfile (frontend builder → backend builder → slim runtime). Container binds to the Tailscale interface on the Acer. Postgres 16 in its own container with persistent volume. Watchtower watches Streamload's container, polls GHCR. Workflow: `git push` → GitHub Actions runs tests → builds amd64+arm64 image → pushes `:latest` + semver tags → Watchtower detects new digest → `docker pull` + recreate.

**Tech Stack:** Docker, docker-compose, GitHub Actions, GitHub Container Registry (ghcr.io), Watchtower, systemd (host-level), Tailscale.

**Spec reference:** §17 (Containerization), §18 (CI/CD), §10 (Dev environment).

**Prerequisite:** Plans 1-5 merged. Acer has Ubuntu Server 24.04 LTS + Docker + Tailscale installed.

---

## File Structure

**New project root files:**
- `Dockerfile` (multi-stage)
- `.dockerignore`
- `docker-compose.yml` (production orchestration)
- `docker-compose.override.yml.example` (local dev override template)
- `.github/workflows/build-and-publish.yml`
- `.github/workflows/test.yml` (PR checks)
- `entrypoint.sh` (container entrypoint, runs migrations then Granian)

**Operations:**
- `docs/deploy.md` — bootstrap runbook for the Acer
- `secret/postgres-password.txt` — gitignored, generated at deploy time

---

## Task 0: Branch + Dockerfile

**Files:** `Dockerfile`, `.dockerignore`, `entrypoint.sh`

- [ ] Branch:

```bash
git checkout main && git pull
git checkout -b feat/v2-deploy-cicd
```

- [ ] **Step 1: Write `.dockerignore`**

```
# VCS
.git/
.gitignore
.gitattributes

# IDE
.idea/
.vscode/

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
venv/
.venv/

# Node
node_modules/

# Frontend builds (rebuilt in container)
web/build/
web/.svelte-kit/

# Tests
tests/
**/test_*.py
.coverage

# Local data
data/
Video/
streamload.log*
.superpowers/

# Secrets
.env
secret/
config.json
login.json

# Documentation
docs/
README.md
*.md

# CI artifacts
.github/
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7

# ============================================================
# Stage 1: Frontend builder
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/web

# Install deps from lockfile only first for cache friendliness
COPY web/package.json web/package-lock.json* ./
RUN npm ci

# Copy source and build static
COPY web/ ./
RUN npm run build
# Output in /app/web/build/

# ============================================================
# Stage 2: Backend wheel builder
# ============================================================
FROM python:3.11-slim AS backend-builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    pkg-config \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --user --no-cache-dir --no-warn-script-location -r requirements.txt

# ============================================================
# Stage 3: Runtime
# ============================================================
FROM python:3.11-slim AS runtime

# System deps for runtime: ffmpeg (post-processing, fingerprint), chromaprint
# (skip intro), libpq5 (asyncpg), CA certs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libchromaprint-tools \
    libpq5 \
    ca-certificates \
    tini \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (uid 1000 to match typical host user)
RUN useradd -m -u 1000 streamload
WORKDIR /app

# Copy backend Python deps
COPY --from=backend-builder --chown=streamload:streamload /root/.local /home/streamload/.local
ENV PATH="/home/streamload/.local/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy backend source
COPY --chown=streamload:streamload streamload/ ./streamload/
COPY --chown=streamload:streamload alembic.ini ./
COPY --chown=streamload:streamload migrations/ ./migrations/
COPY --chown=streamload:streamload streamload.py ./

# Copy frontend build
COPY --from=frontend-builder --chown=streamload:streamload /app/web/build ./web/build/

# Entrypoint runs migrations then exec's Granian (signal-safe)
COPY --chown=streamload:streamload entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import httpx, sys; r = httpx.get('http://localhost:8000/api/health', timeout=3); sys.exit(0 if r.status_code == 200 else 1)" || exit 1

USER streamload
EXPOSE 8000

ENTRYPOINT ["tini", "--", "./entrypoint.sh"]
```

- [ ] **Step 3: Write `entrypoint.sh`**

```bash
#!/bin/sh
set -e

echo "[entrypoint] Running migrations..."
alembic upgrade head

echo "[entrypoint] Starting Streamload API server..."
exec granian \
    --interface asgi \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --loop uvloop \
    streamload.api.app:app
```

- [ ] **Step 4: Build locally to verify**

```bash
docker build -t streamload:local .
docker images | grep streamload
# Expected: image around 250-350 MB
```

- [ ] **Step 5: Smoke run**

```bash
# Need a Postgres for this. For a quick smoke:
docker network create sl-test
docker run -d --name pg-test --network sl-test \
    -e POSTGRES_USER=streamload -e POSTGRES_PASSWORD=streamload -e POSTGRES_DB=streamload \
    postgres:16-alpine
sleep 5
docker run --rm --network sl-test \
    -e DATABASE_URL=postgresql+asyncpg://streamload:streamload@pg-test:5432/streamload \
    -e RESEND_API_KEY=re_dummy \
    -p 8001:8000 streamload:local
# In another shell:
curl http://localhost:8001/api/health
# Expected: {"status":"ok",...}
docker stop pg-test && docker rm pg-test
docker network rm sl-test
```

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore entrypoint.sh
git commit -m "chore(docker): multi-stage Dockerfile with frontend + backend"
```

---

## Task 1: docker-compose for production

**Files:** `docker-compose.yml`, `.env.example` (extended)

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
# Streamload production deployment.
# - Streamload: built from ghcr.io/alfanowski/streamload:${VERSION:-latest}
# - Postgres 16 in companion container
# - Watchtower for automatic updates of streamload only

x-restart-policy: &restart unless-stopped

services:
  streamload:
    image: ghcr.io/alfanowski/streamload:${STREAMLOAD_VERSION:-latest}
    container_name: streamload
    restart: *restart
    depends_on:
      postgres:
        condition: service_healthy
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+asyncpg://streamload:${POSTGRES_PASSWORD}@postgres:5432/streamload
    volumes:
      - ./data:/app/data
      - ./secret:/app/secret:ro
      - ./config.json:/app/config.json:ro
      - ./domains.json:/app/domains.json:ro
      - ./domains.json.sig:/app/domains.json.sig:ro
    ports:
      # Bind to the Tailscale interface only. Replace 100.x.y.z with your
      # Acer's tailnet IP, or use 0.0.0.0 if Tailscale ACLs already gate.
      - "${BIND_HOST:-127.0.0.1}:8000:8000"
    networks:
      - streamload-net
    labels:
      com.centurylinklabs.watchtower.enable: "true"

  postgres:
    image: postgres:16-alpine
    container_name: streamload-postgres
    restart: *restart
    environment:
      POSTGRES_USER: streamload
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: streamload
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U streamload"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - streamload-net
    # Postgres should NOT be auto-updated (data risk on major version bumps)
    labels:
      com.centurylinklabs.watchtower.enable: "false"

  watchtower:
    image: containrrr/watchtower:latest
    container_name: streamload-watchtower
    restart: *restart
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    environment:
      WATCHTOWER_POLL_INTERVAL: 300
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_LABEL_ENABLE: "true"
      WATCHTOWER_INCLUDE_RESTARTING: "true"
      WATCHTOWER_NOTIFICATIONS_LEVEL: info
    labels:
      # Don't update watchtower itself (avoid update-during-update edge cases)
      com.centurylinklabs.watchtower.enable: "false"

volumes:
  postgres-data:

networks:
  streamload-net:
    driver: bridge
```

- [ ] **Step 2: Extend `.env.example`**

```
# Production secrets — generate strong values, keep in .env (gitignored)
POSTGRES_PASSWORD=change-me-strong-random-secret

# Streamload version pin (defaults to :latest if unset)
# STREAMLOAD_VERSION=v0.2.0-alpha.5

# Bind host (defaults to 127.0.0.1 — change to Tailscale IP for prod)
# BIND_HOST=100.x.y.z

# Existing entries below
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload
RESEND_API_KEY=re_REPLACE_ME
TMDB_API_KEY=REPLACE_ME
WEBAUTHN_RP_ID=streamload.YOUR-TAILNET.ts.net
WEBAUTHN_RP_NAME=Streamload
WEBAUTHN_ORIGIN=https://streamload.YOUR-TAILNET.ts.net
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore(docker): production compose stack with Watchtower"
```

---

## Task 2: GitHub Actions test workflow

**Files:** `.github/workflows/test.yml`

- [ ] Write workflow:

```yaml
name: Test

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: streamload
          POSTGRES_PASSWORD: streamload
          POSTGRES_DB: streamload_test
        ports: ['5432:5432']
        options: >-
          --health-cmd="pg_isready -U streamload"
          --health-interval=5s
          --health-timeout=3s
          --health-retries=10
    env:
      DATABASE_URL_TEST: postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: 'pip' }

      - name: Install system deps
        run: sudo apt-get update && sudo apt-get install -y libchromaprint-tools

      - name: Install Python deps
        run: pip install -r requirements-dev.txt

      - name: Run tests
        run: pytest -q --tb=short

  test-frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: web } }
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with: { node-version: '20', cache: 'npm', cache-dependency-path: web/package-lock.json }

      - run: npm ci
      - run: npm run check
      - run: npm run test:unit -- --run
        if: hashFiles('web/vitest.config.*') != ''
      - run: npm run build
```

- [ ] Commit `ci: GitHub Actions test workflow`.

---

## Task 3: GitHub Actions build + publish workflow

**Files:** `.github/workflows/build-and-publish.yml`

- [ ] Write workflow:

```yaml
name: Build & Publish

on:
  push:
    branches: [main]
    tags: ['v*.*.*']

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # for changelog generation

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract image metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest,enable={{is_default_branch}}
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}
            type=sha,prefix=,format=short

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  release:
    needs: build-and-push
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }

      - name: Generate changelog
        id: changelog
        uses: orhun/git-cliff-action@v3
        with:
          config: cliff.toml
          args: --latest --strip header
        continue-on-error: true

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          body: ${{ steps.changelog.outputs.content || 'See commits.' }}
          token: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] Optional: add `cliff.toml` for changelog generation:

```toml
[changelog]
header = "# Changelog\n\n"
body = """
{% for group, commits in commits | group_by(attribute="group") %}
## {{ group | upper_first }}
{% for commit in commits %}
- {{ commit.message }}
{% endfor %}
{% endfor %}
"""
trim = true

[git]
conventional_commits = true
```

- [ ] Commit `ci: build + publish workflow with multi-arch + release`.

---

## Task 4: First push triggers build (verification)

- [ ] Push branch:

```bash
git push -u origin feat/v2-deploy-cicd
```

- [ ] Open a PR or merge to main. Verify GitHub Actions:
  - Test workflow runs on PR
  - Build workflow runs on push to main
  - Image appears in `ghcr.io/alfanowski/streamload` (Packages tab on GitHub)

- [ ] Pull image locally to verify:

```bash
docker pull ghcr.io/alfanowski/streamload:latest
docker run --rm ghcr.io/alfanowski/streamload:latest --version
```

(Note: requires `docker login ghcr.io` if the package is private; default is public for public repos.)

---

## Task 5: First-time Acer bootstrap

**Files:** `docs/deploy.md` (operational runbook)

- [ ] Write the runbook for first deploy on the Acer:

```markdown
# Streamload Production Deployment — First-time Setup

## Prerequisites on the Acer

- Ubuntu Server 24.04 LTS (or any recent x86_64 Linux)
- Docker + docker-compose plugin installed
- Tailscale installed and authenticated to your tailnet, MagicDNS enabled
- Hostname `streamload` taken via `tailscale up --hostname=streamload`

## Bootstrap

```bash
# SSH to the Acer (via Tailscale)
ssh streamload@streamload.YOUR-TAILNET.ts.net

# Create app dir
sudo mkdir -p /opt/streamload && sudo chown $USER /opt/streamload && cd /opt/streamload

# Clone (only docs; runtime image is pulled from GHCR)
git clone --depth=1 https://github.com/alfanowski/Streamload.git . --branch main

# Configure
cp .env.example .env
nano .env
# Set:
#   POSTGRES_PASSWORD=<openssl rand -hex 32>
#   RESEND_API_KEY=<your real Resend key>
#   TMDB_API_KEY=<your real TMDB v3 key>
#   WEBAUTHN_RP_ID=streamload.YOUR-TAILNET.ts.net
#   WEBAUTHN_ORIGIN=https://streamload.YOUR-TAILNET.ts.net
#   STREAMLOAD_VERSION=v0.2.0
#   BIND_HOST=$(tailscale ip -4)

# Copy your config.json (transfer from dev machine)
scp dev:/path/to/Streamload/config.json .

# Restore the signing key from offline backup (USB / password manager)
mkdir -p secret
# Copy domains_signing_key.pem into secret/, chmod 600
chmod 600 secret/domains_signing_key.pem

# Pull and start
docker compose pull
docker compose up -d

# Verify
docker compose logs -f streamload
# Wait for "Starting Streamload API server..."
curl -i http://$(tailscale ip -4):8000/api/health
# Expected: 200 OK

# First user (becomes admin)
curl -X POST http://$(tailscale ip -4):8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alfanowski","email":"you@x.com","password":"strong-password-here"}'

# Trigger initial catalog refresh (admin-only)
curl -X POST http://$(tailscale ip -4):8000/api/admin/catalog/refresh/trending-day \
  -b /tmp/cookies-from-login.txt
```

## Browse from your devices

After bootstrap, visit `https://streamload.YOUR-TAILNET.ts.net` from any device on your tailnet.

Note: HTTPS via Tailscale Funnel is optional. For pure-tailnet usage, plain HTTP works fine
(Tailscale itself encrypts the wire). If you want HTTPS on the public side too, use Tailscale Funnel:

    tailscale funnel 8000

This makes `streamload.YOUR-TAILNET.ts.net` reachable from outside your tailnet too.
**Don't enable funnel** unless you're sure — that's the whole legal posture from §11.

## Day-to-day operations

```bash
# View logs
docker compose logs -f streamload

# Force update to latest
docker compose pull streamload && docker compose up -d streamload

# Pin to a specific version
STREAMLOAD_VERSION=v0.2.0 docker compose up -d streamload

# Rollback (Watchtower will pull latest again next cycle unless you disable)
docker compose pull streamload:v0.1.9 && docker compose up -d streamload

# Backup database
docker exec streamload-postgres pg_dump -U streamload streamload | gzip > \
    backup-$(date +%Y-%m-%d).sql.gz

# Restore database
gunzip -c backup-YYYY-MM-DD.sql.gz | docker exec -i streamload-postgres \
    psql -U streamload streamload
```

## Watchtower behavior

Watchtower polls GHCR every 5 minutes. When a new `:latest` digest is detected:

1. `docker pull` (download in background while old container still running)
2. `docker stop streamload` (SIGTERM, 10s grace)
3. `docker run` with new image
4. Healthcheck waits ~60s for app readiness

Total downtime per update: 5-15s. Active streams reconnect via HLS retry.

## Disabling Watchtower temporarily

```bash
# Pin to a specific version in .env:
echo "STREAMLOAD_VERSION=v0.2.0" >> .env
docker compose up -d streamload
# Watchtower will pull `:v0.2.0` instead of `:latest`. To exclude
# this container from updates entirely, change its label:
docker compose down streamload
# Edit docker-compose.yml: change the label to "false"
docker compose up -d streamload
```
```

- [ ] Commit `docs: production deployment runbook`.

---

## Task 6: Tailscale-aware bind script

**Files:** `scripts/bind-tailscale.sh`

- [ ] Helper script that resolves the Tailscale IP and exports it for compose:

```bash
#!/bin/bash
# Usage: source scripts/bind-tailscale.sh
# Exports BIND_HOST to the Tailscale IP of this host.

if ! command -v tailscale >/dev/null; then
    echo "tailscale CLI not found" >&2
    exit 1
fi

IP=$(tailscale ip -4 | head -1)
if [ -z "$IP" ]; then
    echo "Tailscale not connected (run 'tailscale up')" >&2
    exit 1
fi

echo "Tailscale IP: $IP"
export BIND_HOST="$IP"
```

- [ ] Make executable + commit `chore(scripts): tailscale bind helper`.

---

## Task 7: Production smoke test (manual on Acer)

This task is **manual** — it can't be scripted because it depends on the actual hardware. Document it precisely so it's reproducible.

- [ ] **Step 1: Verify image runs on Acer**

After Task 5 bootstrap:

```bash
# All 3 services up and healthy
docker compose ps
# Expected: streamload (healthy), postgres (healthy), watchtower (running)

# Check Streamload startup time
docker compose logs streamload | grep "Starting"
# Expected: <15 seconds from start

# Memory baseline
docker stats --no-stream streamload
# Expected: <1 GB RAM used at idle
```

- [ ] **Step 2: Verify auto-update works**

```bash
# Push a trivial commit to main from dev (e.g., bump version 0.2.0 → 0.2.1)
git tag -a v0.2.1 -m "test auto-update"
git push origin v0.2.1

# On the Acer, watch Watchtower logs
docker compose logs -f watchtower
# Within 5 minutes, expect:
#   "Found new ghcr.io/alfanowski/streamload:latest image"
#   "Stopping container streamload"
#   "Starting container streamload"

# Verify
curl http://$(tailscale ip -4):8000/api/version
# Expected: {"version":"0.2.1",...}
```

- [ ] **Step 3: Verify backup**

```bash
# Take a manual backup
docker exec streamload-postgres pg_dump -U streamload streamload | \
    gzip > /opt/streamload/data/backup-test.sql.gz
ls -lh /opt/streamload/data/backup-test.sql.gz
# Expected: ~few MB
```

- [ ] **Step 4: Document the Acer's resource usage**

Run a 1-hour load test (1 user watching one stream):

```bash
# Continuously monitor
docker stats streamload streamload-postgres
# Expected:
#   streamload: 1-2 GB RAM, 30-50% CPU during stream, drops to 5-10% idle
#   postgres: <300 MB RAM, <5% CPU
```

Note results in `docs/deploy.md` for future tuning.

- [ ] Once verified, commit any documentation updates.

---

## Task 8: Backup automation

**Files:** `scripts/backup-postgres.sh`, systemd timer

- [ ] Write `scripts/backup-postgres.sh`:

```bash
#!/bin/bash
# Daily Postgres backup, keep last 14 days.
set -e

BACKUP_DIR="/opt/streamload/data/backups"
mkdir -p "$BACKUP_DIR"

DATE=$(date +%Y-%m-%d)
docker exec streamload-postgres pg_dump -U streamload streamload | \
    gzip > "$BACKUP_DIR/streamload-$DATE.sql.gz"

# Prune older than 14 days
find "$BACKUP_DIR" -name "streamload-*.sql.gz" -mtime +14 -delete

echo "Backup complete: $BACKUP_DIR/streamload-$DATE.sql.gz"
```

- [ ] systemd timer (on the Acer, document in `docs/deploy.md`):

```
# /etc/systemd/system/streamload-backup.service
[Unit]
Description=Streamload Postgres backup
After=docker.service

[Service]
Type=oneshot
User=streamload
ExecStart=/opt/streamload/scripts/backup-postgres.sh

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

- [ ] Commit `chore(ops): daily Postgres backup script + systemd timer`.

---

## Task 9: GitHub Action — release notes generator

**Files:** `cliff.toml`, hook into existing `build-and-publish.yml`

This was already partially included in Task 3. Make sure it works:

- [ ] Verify `git-cliff-action` runs on tag push:

```bash
git tag -a v0.2.1-alpha -m "test release notes"
git push origin v0.2.1-alpha
```

Check GitHub Actions log → Release step → confirm GitHub Release page has changelog.

- [ ] If issues, refine `cliff.toml` keywords (`feat`, `fix`, `docs`, etc. mapped to friendly headers).

---

## Task 10: Update version + bump

- [ ] Bump `streamload/version.py` to `0.2.0`:

```python
__version__ = "0.2.0"
```

- [ ] Update `README.md`:
  - Add deployment quickstart pointing to `docs/deploy.md`
  - Update badge to v0.2.0
  - Update "Stack" section with new tech (FastAPI, SvelteKit, Postgres, Resend, Vidstack)

- [ ] Commit `chore: bump version to v0.2.0 + update README`.

---

## Task 11: Final merge + GA tag

- [ ] Run all CI checks (push branch, watch GHA):

```bash
git push origin feat/v2-deploy-cicd
```

Verify all green.

- [ ] Merge to main:

```bash
git checkout main
git merge --no-ff feat/v2-deploy-cicd -m "Merge branch 'feat/v2-deploy-cicd'

Plan 6 of Streamload v2: Containerization + CI/CD + Production Deployment.

Includes:
* Multi-stage Dockerfile (frontend builder → backend builder → slim runtime)
* docker-compose.yml with Streamload + Postgres + Watchtower
* GitHub Actions test workflow (PR + main pushes)
* GitHub Actions build & publish workflow (multi-arch amd64+arm64 → GHCR)
* Tag-driven GitHub Releases with auto-generated changelogs (git-cliff)
* Watchtower auto-update strategy (5-min poll, semver-aware)
* First-time Acer bootstrap runbook (docs/deploy.md)
* Daily Postgres backup script + systemd timer
* Tailscale-aware bind helper

End state: pushing to main triggers test → build → push to ghcr.io.
Watchtower on the Acer pulls within 5 min and auto-deploys with ~10s downtime.

Spec: §17 + §18
Plan: docs/superpowers/plans/2026-05-08-streamload-v2-plan-6-deploy-cicd.md"

git push origin main
git tag -a v0.2.0 -m "Streamload v0.2.0 — Web platform

Full v2 release: TMDB-driven catalog, multi-user web app with login,
PWA-installable, AirPlay + Cast support, Cinematic Dark visual identity,
Skip Intro detection, Watchtower-based auto-update.

See https://github.com/alfanowski/Streamload/releases/tag/v0.2.0 for changelog."
git push origin v0.2.0
```

- [ ] Verify the v0.2.0 release on GitHub Releases page.

- [ ] Verify Watchtower pulls v0.2.0 on the Acer (within 5 min).

- [ ] Visit `https://streamload.<tailnet>.ts.net` from your iPhone, install PWA, watch a movie. **Celebrate.** 🎉

---

## Self-Review Checklist

- [ ] Image builds clean for both amd64 and arm64
- [ ] Image size <300 MB compressed (verify on `docker images`)
- [ ] `docker compose up` brings up all 3 services healthy
- [ ] First-time bootstrap on Acer follows the runbook with no surprises
- [ ] GitHub Actions test workflow passes on every PR
- [ ] GitHub Actions build workflow runs and publishes on main push
- [ ] Watchtower successfully detects + applies a deliberate version bump in <10 min
- [ ] Active streams reconnect cleanly after auto-update (player retries HLS segments)
- [ ] Backup runs nightly and keeps last 14 days
- [ ] No `Co-Authored-By` trailers in any commit on this branch
- [ ] v0.2.0 tagged + GitHub Release created
- [ ] README updated with v2 quickstart

---

## What's done

After Plan 6 merge, **Streamload v2 is live**:

- Web app on `https://streamload.<tailnet>.ts.net`
- Multi-user (you + family)
- TMDB-driven catalog, ~150 titles across 8+ collection rows
- 13 source services with auto-rank + manual override
- HLS streaming + DRM decrypt + cache
- PWA installable on iOS/Android
- AirPlay + Chromecast
- Skip Intro auto-detection
- Continue watching, favorites, watchlist
- Auto-update via GitHub Actions + Watchtower
- Daily backup
- Domain rotation handled by v1 resolver (still in place)

## Future improvements (post-v2.0)

- Recommendation engine (collaborative filtering or simple "more like this")
- Native mobile apps (if PWA limitations bite)
- Offline downloads (the one feature we explicitly removed — could come back as opt-in)
- Live TV / linear streaming
- Watch parties (real-time co-watch)
- Trakt / Letterboxd integration for watch history sync
- Smart TV apps (Apple TV, Android TV native)
- Multi-server deployment (if usage grows beyond a single Acer)
