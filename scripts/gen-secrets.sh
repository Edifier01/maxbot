#!/usr/bin/env bash
# Генерация секретов для .env (запускать на VPS или локально)
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
echo "JWT_SECRET=$(openssl rand -hex 32)"
echo "INTERNAL_SERVICE_TOKEN=$(openssl rand -hex 32)"
