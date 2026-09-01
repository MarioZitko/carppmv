# Deployment

Deploys the stack (Postgres, FastAPI backend with Playwright, Next.js
frontend) to a single VPS with Docker Compose. Written against a Hetzner CAX11
(2 vCPU / 4 GB ARM, €6/mo) but works on any VPS with Docker installed — ARM or
x86.

TLS and public routing are **not** handled by Compose. Every service binds to
localhost only —

| Service | Bound to |
|---|---|
| backend | `127.0.0.1:8011` |
| frontend | `127.0.0.1:3011` |
| db | `127.0.0.1:5433` |

— and a reverse proxy on the host (CloudPanel, in the current setup) terminates
HTTPS and forwards to those ports. Nothing in this repo configures that proxy.

---

## 1. Buy a domain

Let's Encrypt issues certificates for domain names, not bare IPs, so you need
one. Any registrar works (Namecheap, Porkbun, Cloudflare Registrar) — roughly
$8–12/year.

Once purchased, add two DNS **A records** pointing at your VPS's public IP:

| Type | Name | Value |
|---|---|---|
| A | `yourdomain.com` (or `@`) | `<VPS_IP>` |
| A | `api.yourdomain.com` | `<VPS_IP>` |

DNS propagation can take a few minutes to a few hours.

---

## 2. Provision the VPS

SSH in and install Docker:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # re-login after this
```

Recommended: add a swap file so Playwright/Chromium doesn't get OOM-killed
under memory pressure on a small VPS.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Open firewall ports 80 and 443 (and 22 for SSH) if you're running `ufw` or a
cloud-provider firewall.

---

## 3. Clone the repo and configure environment

```bash
git clone <your-repo-url> carPPMV
cd carPPMV
cp .env.example .env
```

Edit `.env`:

- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — pick real credentials,
  not the defaults.
- `CORS_ALLOW_ORIGINS=https://yourdomain.com` — must match the frontend's
  public origin or browser requests will be rejected.
- `OPENROUTER_API_KEY` — only needed if you run catalogue ingestion.
- Leave `DATABASE_URL` as-is; `docker-compose.yml` overrides it to point at
  the `db` service on the Docker network.

Set the frontend's build-time API URL (used by `docker-compose.yml`'s
`frontend` build args):

```bash
echo "NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com" >> .env
```

---

## 4. Build and start everything

```bash
docker compose up -d --build
```

This builds and starts, in order: `db` (Postgres, waits for healthcheck),
`backend` (FastAPI + Playwright/Chromium) and `frontend` (Next.js standalone
build).

First build takes a few minutes (Playwright downloads Chromium + system
deps). Check status:

```bash
docker compose ps
docker compose logs -f backend
curl -sS localhost:3011 >/dev/null && echo "frontend up"
curl -sS localhost:8011/docs >/dev/null && echo "backend up"
```

---

## 4b. Point the reverse proxy at it

In CloudPanel (or whatever proxy you use), create two sites and proxy them to
the localhost ports above, then issue Let's Encrypt certificates for both:

| Hostname | Proxies to |
|---|---|
| `yourdomain.com` | `http://127.0.0.1:3011` |
| `api.yourdomain.com` | `http://127.0.0.1:8011` |

`CORS_ALLOW_ORIGINS` must list the frontend origin exactly, and the frontend
is built with `NEXT_PUBLIC_API_BASE_URL` baked in — change either one and you
have to rebuild the frontend image, not just restart it.

Visit `https://yourdomain.com` — the page should load and reach the API.

---

## 5. Set up automatic deploys (optional)

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) SSHes into the
VPS on every push to `main` and re-runs `docker compose up -d --build`.

Add these repo secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `VPS_HOST` | VPS public IP or hostname |
| `VPS_USER` | SSH user (e.g. `root` or a deploy user) |
| `VPS_SSH_KEY` | Private key with access to that user (no passphrase) |
| `VPS_PORT` | SSH port, if not 22 (optional) |
| `VPS_APP_DIR` | Absolute path to the cloned repo on the VPS, e.g. `/home/deploy/carPPMV` |

Generate a dedicated deploy key rather than reusing your personal one:

```bash
ssh-keygen -t ed25519 -f deploy_key -N ""
# copy deploy_key.pub into the VPS's ~/.ssh/authorized_keys
# paste the contents of deploy_key (private) into the VPS_SSH_KEY secret
```

After this, every merge to `main` redeploys automatically.

---

## Day-to-day operations

```bash
# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Restart a single service
docker compose restart backend

# Rebuild after a manual pull
git pull && docker compose up -d --build

# Shell into a running container
docker compose exec backend bash

# Back up the database
docker compose exec db pg_dump -U <POSTGRES_USER> <POSTGRES_DB> > backup.sql
```

---

## Troubleshooting

- **Certificate issuance fails** — DNS hasn't propagated yet, or ports 80/443
  aren't open on the VPS firewall. Check the proxy's own logs, not Compose's.
- **502 from the proxy** — the container crashed or is still starting; check
  `docker compose logs backend`. Common cause: `DATABASE_URL` mismatch or
  Postgres not yet healthy. Confirm the port is actually listening with
  `curl localhost:8011/docs`.
- **Browser CORS errors** — `CORS_ALLOW_ORIGINS` doesn't match the frontend's
  real origin, or the frontend image was built with the wrong
  `NEXT_PUBLIC_API_BASE_URL`. The latter needs a rebuild, not a restart.
- **Playwright errors about missing libraries** — rebuild the `backend`
  image; `playwright install --with-deps chromium` in the `Dockerfile`
  should cover this, but a stale image won't have it.
- **OOM kills during scraping** — confirm the swap file from step 2 is
  active (`swapon --show`); Chromium is memory-hungry on small VPS plans.
