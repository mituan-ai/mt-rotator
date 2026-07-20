# MT Rotator

[中文](README.md) | **English**

An A-share ETF strategy-advice and self-directed paper-trading system built on free, real daily market data.

MT Rotator is available to invited users. Strategies provide account-aware advice, but every order must be confirmed by the user. The system does not connect to brokers or place live trades.

## Features

- Administrator-managed invitations with per-user data isolation.
- Searchable Sina Finance ETF catalog with daily bars, turnover, settlement rules, and data status.
- Three versioned strategies: trend rotation, relative momentum, and moving-average trend.
- One self-directed paper account per user with CNY 100,000 initial capital.
- Estimated next-session open execution with board lots, commissions, slippage, and T+0/T+1 sellability rules.
- Immutable orders, fills, position lots, and cash ledger.
- Non-anonymous return rankings calculated at a common NAV cutoff date.
- Integrated administration for invitations, users, market-data jobs, strategies, and audit logs.

Market data comes exclusively from the free Sina Finance interfaces exposed through AKShare. The application uses daily data, does not provide real-time quotes, and marks every fill as an estimate.

## Local Setup

### 1. Prerequisites

Install only:

- Git
- Docker Engine
- Docker Compose plugin, using the `docker compose` command

For Ubuntu, follow [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Verify the installation:

```bash
docker --version
docker compose version
```

If Docker reports `/var/run/docker.sock: permission denied`, add your user to the `docker` group, then sign out and back in:

```bash
sudo usermod -aG docker "$USER"
```

### 2. Clone and configure

```bash
git clone https://github.com/mituan-ai/mt-rotator.git
cd mt-rotator
cp .env.example .env
openssl rand -hex 32
```

Edit `.env` and replace at least these values:

```env
DJANGO_SECRET_KEY=the-random-value-generated-above
POSTGRES_PASSWORD=a-separate-strong-database-password
```

For local `https://localhost` access, keep the remaining domain settings from `.env.example`.

### 3. Start the complete stack

```bash
docker compose up --build -d --wait
docker compose ps
```

Docker Compose starts PostgreSQL, Redis, the Django API, Celery Worker, Celery Beat, and Caddy. A one-shot `migrate` service applies database migrations before the application starts.

Check readiness:

```bash
curl -k https://localhost/api/v1/health/ready
```

A response containing `{"status":"ready",...}` means the core services are ready.

### 4. Create the first administrator

```bash
docker compose exec api python manage.py create_admin \
  --email admin@example.com \
  --display-name Administrator
```

The command prompts for and confirms the password. It does not store the password in `.env` or shell history.

### 5. Sign in and import market data

Open [https://localhost](https://localhost). Caddy creates a local certificate, so the browser may show an untrusted-certificate warning in the local environment.

After signing in as the administrator, open the Administration page:

1. Create one-time registration links under Invitations.
2. Select `Backfill 24 months` under Data Status.
3. Wait for the job to finish before using ETFs, Advice, Trading, Backtests, and Rankings.

The initial import accesses the free provider sequentially and with rate limiting. Its duration depends on the ETF count and Sina availability. A failed or interrupted job can be submitted again; the importer resumes missing ranges.

### Common local commands

```bash
# Inspect services and logs
docker compose ps
docker compose logs -f api worker beat

# Rebuild and start changed code
docker compose up --build -d --wait

# Stop services without deleting the PostgreSQL named volume
docker compose down

# Backend, frontend, and browser checks
make test
make e2e
```

Do not run `docker compose down -v`; it deletes the project's database volume.

## Tencent Cloud Production Deployment

### Required order

1. Choose the final domain and identify the server's public IP address.
2. Point the domain's A record to the server. Remove an incorrect AAAA record when IPv6 is not in use.
3. Allow TCP `80`, TCP `443`, and UDP `443` in the Tencent Cloud security group.
4. Install Docker, Compose, Git, restic, and `flock` on the server.
5. Publish a GitHub version so CI can build the matching GHCR images.
6. Configure the production `.env` and off-server backups.
7. Run the initial deployment, create the administrator, and backfill market data.
8. Verify a backup restoration before inviting users.

Choose the domain before starting Caddy in production. Once DNS points to the server and ports `80/443` are reachable, Caddy obtains and renews a public HTTPS certificate automatically. You do not need to upload certificate files manually.

### 1. Install server dependencies

On the Tencent Cloud Ubuntu server, install Git, restic, `flock`, and Docker from Docker's official repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git restic util-linux
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

End the SSH session and sign in again so the `docker` group membership takes effect, then verify:

```bash
docker --version
docker compose version
```

### 2. Publish a version

Pushing `main` runs CI, but only a `v*` tag builds and publishes production images:

```bash
git push origin main
git tag v1.0.0
git push origin v1.0.0
```

Wait for the backend, frontend, E2E, Docker, and image-scanning jobs to pass in GitHub Actions. Images are published as:

```text
ghcr.io/mituan-ai/mt-rotator-api
ghcr.io/mituan-ai/mt-rotator-web
```

If the GHCR packages are private, run `docker login ghcr.io` on the server first.

### 3. Prepare the server directory

```bash
sudo mkdir -p /opt/mt-rotator
sudo chown "$USER":"$USER" /opt/mt-rotator
git clone https://github.com/mituan-ai/mt-rotator.git /opt/mt-rotator
cd /opt/mt-rotator
git checkout v1.0.0
cp .env.example .env
```

### 4. Configure production

For a domain such as `etf.example.com`, set at least these values in `.env`:

```env
DJANGO_SECRET_KEY=a-random-secret-with-at-least-50-characters
POSTGRES_PASSWORD=a-separate-strong-database-password
DJANGO_ALLOWED_HOSTS=etf.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://etf.example.com
PUBLIC_BASE_URL=https://etf.example.com
SITE_ADDRESS=etf.example.com
CADDY_HEALTH_URL=https://etf.example.com/api/v1/health/live
```

Keep `DJANGO_DEBUG=false`, `DJANGO_SECURE_COOKIES=true`, and `DJANGO_SECURE_SSL_REDIRECT=true`.

Do not let Nginx, Apache, or a control panel occupy public ports `80/443`. A Tencent Cloud CDN or load balancer changes where TLS terminates and requires a separate proxy configuration instead of the direct setup above.

### 5. Configure off-server backups

The update command requires restic to store PostgreSQL backups outside the VPS. Create `/etc/mt-rotator/backup.env`:

```bash
sudo mkdir -p /etc/mt-rotator
sudo touch /etc/mt-rotator/backup.env
sudo chmod 600 /etc/mt-rotator/backup.env
```

Its contents depend on the S3-compatible object storage in use. For example:

```env
RESTIC_REPOSITORY=s3:s3.example.com/mt-rotator
RESTIC_PASSWORD_FILE=/etc/mt-rotator/restic-password
```

Store object-storage credentials in the same file, never in Git. Initialize the repository:

```bash
set -a
. /etc/mt-rotator/backup.env
set +a
restic snapshots >/dev/null 2>&1 || restic init
```

### 6. Run the initial deployment

```bash
cd /opt/mt-rotator
./ops/mt-rotator update v1.0.0
./ops/mt-rotator status
docker compose exec api python manage.py create_admin \
  --email admin@example.com \
  --display-name Administrator
```

Open the production domain, sign in, and run `Backfill 24 months` on the Administration page. Then install the daily backup and monthly restore-verification timers:

```bash
sudo cp infra/systemd/mt-rotator-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  mt-rotator-backup.timer \
  mt-rotator-restore-verify.timer
```

Run one manual verification:

```bash
./ops/mt-rotator backup
./ops/mt-rotator restore-verify
```

### Automatic updates after a release

Configure these secrets in the GitHub `production` Environment:

```text
PRODUCTION_HOST
PRODUCTION_USER
PRODUCTION_SSH_PRIVATE_KEY
PRODUCTION_KNOWN_HOSTS
```

`PRODUCTION_SSH_PRIVATE_KEY` must be a dedicated deployment key whose public key is present in the deployment user's `authorized_keys`. `PRODUCTION_KNOWN_HOSTS` must contain the manually verified SSH host key; the workflow does not trust a freshly scanned host key.

After a semantic version tag is pushed, CI runs the tests, builds and scans both images, publishes immutable release images, and updates the server automatically:

```bash
git tag v1.1.0
git push origin v1.1.0
```

The deployment job uses its short-lived GitHub token to pull GHCR images and logs out from the registry afterward. The server still runs `./ops/mt-rotator update`, which acquires a deployment lock, creates an off-server backup, pins image digests, applies migrations, and waits for health checks. A failed update restores the previous application images. It does not delete the PostgreSQL volume or reverse database migrations automatically.

To roll back application images:

```bash
./ops/mt-rotator rollback
```

See [docs/operations.md](docs/operations.md) for backup, recovery, and incident procedures, and [docs/architecture.md](docs/architecture.md) for domain boundaries.

## Development Checks

Run the repository checks locally:

```bash
make test
make e2e
```

Backend development uses Python 3.12 and [uv](https://docs.astral.sh/uv/):

```bash
cd backend
uv sync --all-groups
MT_TESTING=1 uv run pytest
```

Frontend development uses Node.js 22:

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

## Data and Risk

The free data provider may be delayed, change, or become temporarily unavailable. A failure for one ETF pauses that instrument; insufficient primary-pool coverage pauses new advice while preserving historical access. Paper-trading results and strategy advice are for research only and are not investment advice.

## License

[MIT](LICENSE)
