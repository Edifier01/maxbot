#!/usr/bin/env bash
# Одноразовая подготовка VPS для автодеплоя из GitHub Actions.
# Запуск на сервере от root или через sudo:
#   curl -fsSL ... | bash
#   или: bash scripts/bootstrap-vps.sh /opt/maxsender git@github.com:Edifier01/maxbot.git
set -euo pipefail
umask 077

DEPLOY_PATH="${1:-/opt/maxsender}"
REPO_URL="${2:-git@github.com:Edifier01/maxbot.git}"

if [[ -n "${DEPLOY_USER:-}" ]]; then
  :
elif [[ -n "${SUDO_USER:-}" ]]; then
  DEPLOY_USER="$SUDO_USER"
elif [[ "${USER:-}" != "root" && -n "${USER:-}" ]]; then
  DEPLOY_USER="$USER"
else
  echo "Укажите DEPLOY_USER при запуске от root" >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запустите от root: sudo bash $0"
  exit 1
fi

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "Пользователь deployment не найден: $DEPLOY_USER" >&2
  exit 1
fi
DEPLOY_HOME="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
DEPLOY_GROUP="$(id -gn "$DEPLOY_USER")"
if [[ -z "$DEPLOY_HOME" || ! -d "$DEPLOY_HOME" ]]; then
  echo "Домашний каталог deployment не найден: $DEPLOY_HOME" >&2
  exit 1
fi

run_as_deploy() {
  runuser -u "$DEPLOY_USER" -- env HOME="$DEPLOY_HOME" "$@"
}

if ! command -v docker >/dev/null; then
  apt-get update -qq
  apt-get install -y ca-certificates curl git gnupg
  install -m 0755 -d /etc/apt/keyrings
  . /etc/os-release
  case "${ID:-}" in
    ubuntu|debian) ;;
    *) echo "Неподдерживаемый дистрибутив для Docker APT repo: ${ID:-unknown}" >&2; exit 1 ;;
  esac
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" \
    | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  arch="$(dpkg --print-architecture)"
  echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$ID ${VERSION_CODENAME:?} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  usermod -aG docker "$DEPLOY_USER"
fi

KEY_DIR="$DEPLOY_HOME/.ssh"
KEY_FILE="$KEY_DIR/github_deploy"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" "$KEY_DIR"

if [[ ! -f "$KEY_FILE" ]]; then
  run_as_deploy ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" \
    -C "maxsender-deploy@$(hostname)"
fi

echo
echo "=== Deploy key для GitHub (только чтение) ==="
echo "Settings → Deploy keys → Add deploy key:"
cat "${KEY_FILE}.pub"
echo

if [[ "$REPO_URL" == git@* || "$REPO_URL" == ssh://* ]]; then
  echo "=== Проверка SSH authorization до clone ==="
  if ! run_as_deploy env GIT_SSH_COMMAND="ssh -i $KEY_FILE -o IdentitiesOnly=yes" \
    git ls-remote "$REPO_URL" HEAD >/dev/null; then
    echo "Deploy key не авторизован для $REPO_URL; добавьте public key и запустите bootstrap снова." >&2
    exit 1
  fi
fi

if [[ ! -d "$DEPLOY_PATH/.git" ]]; then
  if [[ -e "$DEPLOY_PATH" ]] && [[ -n "$(find "$DEPLOY_PATH" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "Каталог deployment существует и не пуст: $DEPLOY_PATH" >&2
    exit 1
  fi
  install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" "$DEPLOY_PATH"
  run_as_deploy env GIT_SSH_COMMAND="ssh -i $KEY_FILE -o IdentitiesOnly=yes" \
    git clone "$REPO_URL" "$DEPLOY_PATH"
fi

chown -R "$DEPLOY_USER:$DEPLOY_GROUP" "$DEPLOY_PATH"

echo "=== Git remote на сервере ==="
run_as_deploy git -C "$DEPLOY_PATH" remote set-url origin "$REPO_URL" 2>/dev/null || true

ENV_FILE="$DEPLOY_PATH/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  install -m 600 "$DEPLOY_PATH/.env.example" "$ENV_FILE"
  chown "$DEPLOY_USER:$DEPLOY_GROUP" "$ENV_FILE"
  echo "Создан $ENV_FILE — заполните DOMAIN, JWT_SECRET, пароли."
fi
chmod 600 "$ENV_FILE"

echo
echo "=== Секреты GitHub Actions (Settings → Secrets → Actions) ==="
echo "DEPLOY_HOST     = $(curl -fsSL ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo "DEPLOY_USER     = $DEPLOY_USER"
echo "DEPLOY_PATH     = $DEPLOY_PATH"
echo "DEPLOY_SSH_KEY  = приватный ключ для SSH *на сервер* (см. docs ниже)"
echo
echo "Первый деплой вручную:"
echo "  cd $DEPLOY_PATH && nano .env && bash scripts/deploy.sh"
