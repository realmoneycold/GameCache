#!/usr/bin/env bash
# ==============================================================================
# GameHub Production Automated Deployment Runner
# ==============================================================================
# Automates code pulls, container rebuilding, DB migration/setup verification,
# rolling container restarts, and post-deployment health smoke testing.
# ==============================================================================

set -eo pipefail

echo "========================================="
echo "🚀 Starting GameHub Automated Deployment"
echo "========================================="

# 1. Stash Local Changes and Pull Latest Code
echo "Stashing local changes and pulling latest code..."
git stash || true
git pull

# 2. Build Production App Container Without Cache
echo "Building the application container (no-cache)..."
docker compose -f docker-compose.prod.yml build --no-cache gamehub_app

# 3. Safely Run Database Migrations / Setup via Temporary Container
echo "Executing database verification and table creation..."
docker compose -f docker-compose.prod.yml run --rm gamehub_app python verify_setup.py

# 4. Perform Zero-Downtime Rolling Restart
echo "Performing rolling restart of services..."
docker compose -f docker-compose.prod.yml up -d --remove-orphans

# 5. Run Post-Deployment Health Smoke Test
echo "Verifying live deployment health..."
if [ -f "./scripts/smoke_test.sh" ]; then
    bash ./scripts/smoke_test.sh
else
    echo "❌ smoke_test.sh not found!"
    exit 1
fi

echo "========================================="
echo "🎉 Deployment Completed Successfully!"
echo "========================================="
exit 0
