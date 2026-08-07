#!/usr/bin/env bash
# Одноразовая подготовка VPS для автодеплоя из GitHub Actions.
# Запуск на сервере от root или через sudo:
#   curl -fsSL ... | bash
#   или: bash scripts/bootstrap-vps.sh /opt/maxsender git@github.com:Edifier01/maxbot.git
set -euo pipefail

DEPLOY_PATH="${1:-/opt/maxsender}"
REPO_URL="${2:-git@github.com:Edifier01/maxbot.git}"
DEPLOY_USER="${SUDO_USER:-$USER}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запустите от root: sudo bash $0"
  exit 1
fi

if ! command -v docker >/dev/null; then
  apt-get update -qq
  apt-get install -y ca-certificates curl git
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker "$DEPLOY_USER"
fi

if [[ ! -d "$DEPLOY_PATH/.git" ]]; then
  mkdir -p "$(dirname "$DEPLOY_PATH")"
  sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$DEPLOY_PATH"
fi

chown -R "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_PATH"

KEY_DIR="/home/$DEPLOY_USER/.ssh"
KEY_FILE="$KEY_DIR/github_deploy"
mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"

if [[ ! -f "$KEY_FILE" ]]; then
  sudo -u "$DEPLOY_USER" ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" -C "maxsender-deploy@$(hostname)"
fi

echo
echo "=== Deploy key для GitHub (только чтение) ==="
echo "Settings → Deploy keys → Add deploy key:"
cat "${KEY_FILE}.pub"
echo
echo "=== Git remote на сервере ==="
sudo -u "$DEPLOY_USER" git -C "$DEPLOY_PATH" remote set-url origin "$REPO_URL" 2>/dev/null || true

ENV_FILE="$DEPLOY_PATH/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$DEPLOY_PATH/.env.example" "$ENV_FILE"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV_FILE"
  echo "Создан $ENV_FILE — заполните DOMAIN, JWT_SECRET, пароли."
fi

echo
echo "=== Секреты GitHub Actions (Settings → Secrets → Actions) ==="
echo "DEPLOY_HOST     = $(curl -fsSL ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo "DEPLOY_USER     = $DEPLOY_USER"
echo "DEPLOY_PATH     = $DEPLOY_PATH"
echo "DEPLOY_SSH_KEY  = приватный ключ для SSH *на сервер* (см. docs ниже)"
echo
echo "Первый деплой вручную:"
echo "  cd $DEPLOY_PATH && nano .env && bash scripts/deploy.sh"
