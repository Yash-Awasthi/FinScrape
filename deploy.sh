#!/usr/bin/env bash
# =============================================================================
# FinScrape — Full Deployment Script
# Run from the repo root: bash deploy.sh
# =============================================================================
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
section() { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# =============================================================================
# PART 1 — Python scraping pipeline
# =============================================================================
section "Python Pipeline Setup"

cd "$REPO_ROOT"

if [ ! -f ".env" ]; then
  cp .env.example .env
  warn ".env created from .env.example"
  warn "→ Open .env and add your OPENROUTER_API_KEY, then re-run this script."
  exit 1
fi

# Check for the API key
source .env 2>/dev/null || true
if [ -z "$OPENROUTER_API_KEY" ]; then
  warn "OPENROUTER_API_KEY not set in .env — AI analysis will be skipped."
  warn "  push_to_dashboard.py (heuristic mode) will still work."
fi

# Python virtual environment
if [ ! -d "venv" ]; then
  info "Creating Python venv..."
  python3 -m venv venv
fi

info "Activating venv and installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt -q

# Install Playwright Chromium for stealth scrapers
info "Installing Playwright Chromium..."
playwright install chromium --with-deps 2>/dev/null || \
  python -m playwright install chromium 2>/dev/null || \
  warn "Playwright install failed — stealth scrapers (Bloomberg, Reuters, FT, SeekingAlpha) won't work."

info "Python pipeline ready."

# =============================================================================
# PART 2 — Dashboard (Cloudflare Workers)
# =============================================================================
section "Dashboard Deployment (Cloudflare Workers)"

cd "$REPO_ROOT/dashboard"

# Check bun
if ! command -v bun &>/dev/null; then
  error "bun not found. Install it: curl -fsSL https://bun.sh/install | bash, then restart your shell."
fi

# Check wrangler
if ! command -v wrangler &>/dev/null; then
  info "Installing wrangler globally..."
  bun add -g wrangler
fi

info "Installing dashboard dependencies..."
bun install

# Check wrangler login
if ! wrangler whoami &>/dev/null 2>&1; then
  warn "Not logged in to Cloudflare. Running wrangler login..."
  wrangler login
fi

# Apply D1 migrations
info "Applying D1 migrations to remote database..."
wrangler d1 migrations apply fin-scrape-db --remote || \
  warn "D1 migration failed — you may need to create the DB first:"
echo "       wrangler d1 create fin-scrape-db"
echo "       (then copy the database_id into dashboard/wrangler.jsonc)"

# Set secrets
section "Secrets Setup"
warn "You'll be prompted to enter secrets. Press Ctrl+C to skip any optional ones."

echo -n "Enter your API key for event ingestion (leave blank for default 'finscrape-default-key'): "
read -r api_key
if [ -n "$api_key" ]; then
  echo "$api_key" | wrangler secret put API_KEY
else
  info "Using default API key: finscrape-default-key (already set in vars)"
fi

echo -n "Enter your Telegram Bot Token (leave blank to skip): "
read -r telegram_token
if [ -n "$telegram_token" ]; then
  echo "$telegram_token" | wrangler secret put TELEGRAM_BOT_TOKEN
  info "Telegram bot token set."
else
  warn "Skipping Telegram — bot alerts won't work."
fi

# Build and deploy
section "Building and Deploying Dashboard"
info "Building React frontend..."
bun run build

info "Deploying to Cloudflare Workers..."
DEPLOY_OUTPUT=$(wrangler deploy 2>&1)
echo "$DEPLOY_OUTPUT"

# Extract deployed URL
WORKER_URL=$(echo "$DEPLOY_OUTPUT" | grep -oP 'https://[a-z0-9\-]+\.[a-z0-9\-]+\.workers\.dev' | head -1)
if [ -z "$WORKER_URL" ]; then
  warn "Could not extract deployed URL from wrangler output."
  WORKER_URL="https://fin-scrape.<your-subdomain>.workers.dev"
fi

info "Dashboard deployed at: $WORKER_URL"

# Update push_to_dashboard.py with the real URL
cd "$REPO_ROOT"
sed -i "s|FINSCRAPE_DASHBOARD_URL\", \"https://.*\"|FINSCRAPE_DASHBOARD_URL\", \"$WORKER_URL\"|" push_to_dashboard.py
info "Updated push_to_dashboard.py default URL → $WORKER_URL"

# Register Telegram webhook (optional)
if [ -n "$telegram_token" ]; then
  section "Telegram Webhook Registration"
  WEBHOOK_URL="$WORKER_URL/api/telegram/webhook"
  WEBHOOK_RESP=$(curl -s "https://api.telegram.org/bot${telegram_token}/setWebhook?url=${WEBHOOK_URL}")
  if echo "$WEBHOOK_RESP" | grep -q '"ok":true'; then
    info "Telegram webhook registered at $WEBHOOK_URL"
  else
    warn "Telegram webhook registration failed. Do it manually:"
    echo "  curl 'https://api.telegram.org/bot<TOKEN>/setWebhook?url=$WEBHOOK_URL'"
  fi
fi

# =============================================================================
# PART 3 — Test run
# =============================================================================
section "Test Run — Pushing news to dashboard (2hr window)"

cd "$REPO_ROOT"
source venv/bin/activate

info "Running push_to_dashboard.py with 2hr window, 30 articles/source..."
python push_to_dashboard.py \
  --url "$WORKER_URL" \
  --api-key "${api_key:-finscrape-default-key}" \
  --age-hours 2 \
  --limit 30

# =============================================================================
# Summary
# =============================================================================
section "Deployment Complete"

echo ""
echo -e "${BOLD}Dashboard:${NC}  $WORKER_URL"
echo -e "${BOLD}API Key:${NC}    ${api_key:-finscrape-default-key}"
echo ""
echo -e "${BOLD}To run the full AI pipeline:${NC}"
echo "  source venv/bin/activate"
echo "  python -m worker.main --once"
echo ""
echo -e "${BOLD}To run heuristic push only (no AI key needed):${NC}"
echo "  python push_to_dashboard.py --age-hours 2 --limit 30"
echo ""
echo -e "${BOLD}Cron for continuous 2hr-window coverage (every 30 min):${NC}"
echo "  */30 * * * * cd $REPO_ROOT && source venv/bin/activate && python push_to_dashboard.py --age-hours 2 --limit 30 >> /var/log/finscrape.log 2>&1"
echo ""
echo -e "${BOLD}To test AI analysis on dashboard:${NC}"
echo "  Open $WORKER_URL, click any news row → AI Summary tab should populate."
echo ""
