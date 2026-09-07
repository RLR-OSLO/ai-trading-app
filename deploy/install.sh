#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY_URL="https://github.com/RLR-OSLO/ai-trading-app.git"
APP_DIR="/opt/ai-trading-app"
STATE_DIR="/var/lib/ai-trading-app"
ENV_FILE="/etc/ai-trading-app.env"
SERVICE_FILE="/etc/systemd/system/ai-trading-app.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

# Remove the temporary SSH-over-443 route used during setup. Port 22 remains.
rm -f /etc/ssh/sshd_config.d/60-ai-trading-app-port.conf
ufw --force delete allow 443/tcp >/dev/null 2>&1 || true
/usr/sbin/sshd -t
systemctl restart ssh

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 ca-certificates

if ! id trader >/dev/null 2>&1; then
  useradd --system --home-dir "${STATE_DIR}" --create-home \
    --shell /usr/sbin/nologin trader
fi

if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --depth 1 origin main
  git -C "${APP_DIR}" reset --hard origin/main
else
  rm -rf "${APP_DIR}"
  git clone --depth 1 "${REPOSITORY_URL}" "${APP_DIR}"
fi

mkdir -p "${STATE_DIR}"
chown trader:trader "${STATE_DIR}"
chown -R root:root "${APP_DIR}"
chmod -R go-w "${APP_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${APP_DIR}/.env.example" "${ENV_FILE}"
fi
chown root:trader "${ENV_FILE}"
chmod 640 "${ENV_FILE}"

cp "${APP_DIR}/deploy/ai-trading-app.service" "${SERVICE_FILE}"
chmod 644 "${SERVICE_FILE}"
systemctl daemon-reload
systemctl enable --now ai-trading-app.service
sleep 3

if systemctl is-active --quiet ai-trading-app.service; then
  echo "AI_TRADING_MONITOR_READY"
else
  journalctl -u ai-trading-app.service --no-pager -n 30
  exit 1
fi

