#!/usr/bin/env bash
# ==============================================================================
# GameHub Production Smoke-Tester Engine
# ==============================================================================
# Checks the health of the 4 core services: gamehub-app, gamehub-postgres,
# gamehub-redis, gamehub-caddy.
# Returns exit code 0 on success, non-zero on failure.
# ==============================================================================

set -eo pipefail

echo "========================================="
echo "🔍 Starting GameHub Production Smoke Test"
echo "========================================="

# Helper to check if a container is running
check_container() {
    local container_name=$1
    if ! docker ps --filter "name=${container_name}" --filter "status=running" | grep -q "${container_name}"; then
        echo "❌ Container ${container_name} is NOT running!"
        return 1
    fi
    echo "✅ Container ${container_name} is running."
    return 0
}

# 1. Check Container Running Status
FAILED=0
check_container "gamehub-postgres" || FAILED=1
check_container "gamehub-redis" || FAILED=1
check_container "gamehub-app" || FAILED=1
check_container "gamehub-caddy" || FAILED=1

if [ $FAILED -ne 0 ]; then
    echo "❌ Smoke test failed: One or more containers are stopped."
    exit 1
fi

# 2. Probe FastAPI App Health Endpoint Internally
echo "Probing FastAPI /health endpoint..."
if ! docker exec gamehub-app python -c "import urllib.request, json; res = urllib.request.urlopen('http://localhost:8080/health'); data = json.loads(res.read()); assert data['status'] == 'healthy'" 2>/dev/null; then
    echo "❌ FastAPI health check failed or returned invalid response!"
    exit 2
fi
echo "✅ FastAPI /health is healthy."

# 3. Probe Redis Server Connection
echo "Probing Redis connectivity..."
if [ "$(docker exec gamehub-redis redis-cli ping | tr -d '\r')" != "PONG" ]; then
    echo "❌ Redis ping check failed!"
    exit 3
fi
echo "✅ Redis connection is healthy."

echo "========================================="
echo "🎉 GameHub Production Smoke Test PASSED!"
echo "========================================="
exit 0
