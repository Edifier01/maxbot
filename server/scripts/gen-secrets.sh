#!/usr/bin/env bash
# Генерация секретов для server/.env (запускать на VPS или локально)
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
echo "JWT_SECRET=$(openssl rand -hex 32)"
