#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# install-local-api.sh
# Installs and runs the official Telegram Bot API local server on your VPS.
# This removes the 50MB limit — allows up to 2GB uploads.
#
# Requirements: You need API_ID and API_HASH from https://my.telegram.org
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo "=== Telegram Local Bot API Server Setup ==="
echo ""
echo "You need API_ID and API_HASH from https://my.telegram.org/apps"
echo "Log in → API development tools → Create app"
echo ""
read -p "Enter your API_ID: " API_ID
read -p "Enter your API_HASH: " API_HASH
echo ""

# Install dependencies
apt-get update
apt-get install -y \
    build-essential \
    cmake \
    gperf \
    libssl-dev \
    zlib1g-dev \
    libreadline-dev \
    ccache \
    git

# Clone and build telegram-bot-api
cd /tmp
if [ -d "telegram-bot-api" ]; then
    rm -rf telegram-bot-api
fi

git clone --recursive https://github.com/tdlib/telegram-bot-api.git
cd telegram-bot-api

mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX:PATH=/usr/local ..
cmake --build . --target install -j$(nproc)

echo ""
echo "=== Build complete ==="

# Create working directory
mkdir -p /var/lib/telegram-bot-api

# Create systemd service
cat > /etc/systemd/system/telegram-bot-api.service << EOF
[Unit]
Description=Telegram Bot API Local Server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/telegram-bot-api \
    --api-id=${API_ID} \
    --api-hash=${API_HASH} \
    --local \
    --dir=/var/lib/telegram-bot-api \
    --http-port=8081 \
    --log=/var/log/telegram-bot-api.log
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now telegram-bot-api
sleep 3
systemctl status telegram-bot-api

echo ""
echo "=== Done! Local API running on http://localhost:8081 ==="
echo ""
echo "Now add this to /root/ytdl-bot/.env:"
echo "  LOCAL_API_URL=http://localhost:8081"
echo "  MAX_FILE_SIZE_MB=2000"
echo ""
echo "Then restart your bot:"
echo "  systemctl restart ytdl-bot"
