# GameHub Production Deployment & Operations Runbook

This document describes host-level preparations and operational procedures to deploy the GameHub system on your live production VPS.

## 1. VPS Host Docker Setup

To avoid running Docker Compose commands as root or running into permission errors when executing `./scripts/deploy.sh` or `./scripts/smoke_test.sh`, add the system user to the native `docker` system group:

```bash
# 1. Add your system user to the docker group
sudo usermod -aG docker $USER

# 2. Apply group changes immediately in the current terminal session
newgrp docker

# 3. (Optional) Verify rootless docker connection
docker ps
```

---

## 2. Secrets Initialization

Initialize high-entropy production environment variables and replace placeholder values in `.env.prod`:

```bash
# Execute the secrets generator using the virtual environment
venv/bin/python scripts/generate_secrets.py
```
This automatically updates `INTERNAL_API_SECRET_TOKEN` with a cryptographically secure 32-character hexadecimal key.

---

## 3. Launching Automated Deployment

Run the unified deploy runner to perform git pulls, container builds, schema checks, rolling restarts, and live post-deployment health smoke testing:

```bash
# Trigger the automated deployment pipeline
./scripts/deploy.sh
```

---

## 4. Live Health Check Probes

If you need to manually inspect the live container mesh state, run the smoke tester:

```bash
# Run the internal health checks manually
./scripts/smoke_test.sh
```
This script validates:
- Active running states for all 4 containers (`gamehub-app`, `gamehub-postgres`, `gamehub-redis`, `gamehub-caddy`).
- Internal FastAPI `/health` endpoint state.
- Internal Redis socket connectivity and ping response.
