# Deploying PMS (self-host)

PMS ships as a set of Docker containers — `postgres`, `redis`, `backend`
(FastAPI) and `frontend` (Next.js). The simplest production setup runs them with
Docker Compose behind an nginx reverse proxy that terminates TLS. One domain,
one origin: the frontend at `/`, the API under `/api/`.

## Prerequisites

- A Linux host with Docker and the Docker Compose plugin.
- A domain name pointed at the host (an `A` record).
- Ports 80/443 open; a TLS certificate (this guide uses Let's Encrypt / certbot).

## 1. Get the code and configure

```bash
git clone https://github.com/trendbender/pms.git
cd pms
cp .env.example .env
```

Edit `.env` and set, at minimum:

- `JWT_SECRET` — a long random string (e.g. `openssl rand -hex 32`).
- `POSTGRES_PASSWORD` and the matching `DATABASE_URL`.
- `CORS_ORIGINS=https://your-domain.com`
- `NEXT_PUBLIC_API_URL=https://your-domain.com/api`
- `BOOTSTRAP_OWNER_EMAIL` / `BOOTSTRAP_OWNER_PASSWORD` for the first admin.

Optional: `STORAGE_*` (S3-compatible bucket for attachments), `SMTP_*` (outgoing
mail), and `NEXT_PUBLIC_BRAND_NAME` / `_BADGE` / `_URL` to brand the login screen.

> **Never commit `.env`.** It is git-ignored by default.

## 2. Start the stack

```bash
docker compose up -d --build      # backend runs `alembic upgrade head` on boot
docker compose exec backend python -m app.cli seed   # create the first Owner + Workspace
```

Check health: `curl http://127.0.0.1:8000/health`.

For a production deployment, keep the DB and Redis on the internal compose
network and publish only what the reverse proxy needs (or nothing, if nginx runs
on the same host and reaches the containers over `127.0.0.1`). Adjust the
published ports in your compose override to taste.

## 3. Reverse proxy + TLS

Use [`deploy/nginx.example.conf`](../deploy/nginx.example.conf) as a starting
point — replace `your-domain.com` and the upstream ports, then:

```bash
# HTTP-01 challenge served from /var/www/certbot (see the example vhost)
certbot certonly --webroot -w /var/www/certbot -d your-domain.com
nginx -t && systemctl reload nginx
```

Certbot renews automatically; nginx picks up renewed certs on reload.

## 4. Upgrades

```bash
git pull
docker compose up -d --build      # migrations run automatically on backend start
```

## 5. Backups

Back up the Postgres volume regularly. A simple cron job:

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "pms-$(date +%F).sql.gz"
```

Keep backups off-host, and test a restore before you rely on them.

## Notes

- All permission checks run on the backend; the frontend is a thin client.
- HTML must not be cached by the proxy — a stale shell can serve dead JS chunks
  after a deploy (the example vhost handles this).
