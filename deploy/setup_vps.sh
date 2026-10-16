#!/usr/bin/env bash
# ==============================================================================
# deploy/setup_vps.sh — Automated deployment script for komdigi-bot on VPS Singapore
# ==============================================================================
set -euo pipefail

APP_DIR="/home/ubuntu/apps/komdigi-bot"
REPO_URL="${REPO_URL:-https://github.com/organization/komdigi-bot.git}"
MINI_PC_TAILSCALE_IP="${MINI_PC_TAILSCALE_IP:-100.x.y.z}"
PROXY_PORT="${PROXY_PORT:-1080}"

echo "=== [1/6] Preparing Application Directory ==="
mkdir -p /home/ubuntu/apps
if [ -d "$APP_DIR/.git" ]; then
    echo "Existing repository found. Pulling latest master..."
    cd "$APP_DIR"
    git fetch origin master
    git reset --hard origin/master
else
    echo "Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

echo "=== [2/6] Setting Up Python Virtual Environment ==="
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
python3 -m playwright install --with-deps chromium

echo "=== [3/6] Generating Production .env for VPS ==="
if [ ! -f .env ]; then
    cat <<EOF > .env
# ==============================================================
# KOMDIGI Bot Environment Configuration (VPS Singapore 24/7 Node)
# ==============================================================

# LLM Endpoint: Local 9router or remote OpenAI-compatible gateway
LLM_BASE_URL=${LLM_BASE_URL:-http://127.0.0.1:20128/v1}
LLM_API_KEY=${LLM_API_KEY:-your_llm_api_key_here}
LLM_MODEL_VISION=${LLM_MODEL_VISION:-ag/gemini-3.8-flash-high}
LLM_MODEL_REASONING=${LLM_MODEL_REASONING:-ag/gemini-3.8-flash-high}

# TypeSafe AI System One decision pre-gate (Jev)
TYPESAFE_API_KEY=${TYPESAFE_API_KEY:-your_typesafe_api_key_here}

# Hybrid Residential Egress Proxy (Routing through Mini PC via Tailscale Mesh)
PROXY=socks5://${MINI_PC_TAILSCALE_IP}:${PROXY_PORT}

SOLVER_POLICY=hybrid
INTERVAL_SECONDS=1800
JITTER_SECONDS=180
EOF
    echo "Created .env template. Please verify credentials in $APP_DIR/.env."
fi

echo "=== [4/6] Verifying Connectivity to Mini PC Residential Proxy ==="
if nc -z -w 3 "$MINI_PC_TAILSCALE_IP" "$PROXY_PORT" 2>/dev/null; then
    echo "SUCCESS: Mini PC Residential Proxy at $MINI_PC_TAILSCALE_IP:$PROXY_PORT is reachable!"
else
    echo "WARNING: Mini PC Residential Proxy at $MINI_PC_TAILSCALE_IP:$PROXY_PORT is not reachable yet."
    echo "Ensure start_residential_proxy.py is running on the Mini PC."
fi

echo "=== [5/6] Registering and Starting PM2 Daemon ==="
pm2 delete komdigi-bot-worker 2>/dev/null || true
pm2 start deploy/ecosystem.config.js
pm2 save

echo "=== [6/6] Deployment Completed Successfully ==="
pm2 status komdigi-bot-worker
