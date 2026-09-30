#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  # Hex is safe inside PostgreSQL connection URLs and Compose interpolation.
  password_pair=$(docker run --rm python:3.13-slim-bookworm python -c 'import secrets; print(secrets.token_hex(24) + ":" + secrets.token_hex(24))')
  admin_pass=${password_pair%%:*}
  database_pass=${password_pair#*:}
  umask 077
  sed -e "s/replace-with-a-long-random-password/$admin_pass/" \
      -e "s/replace-with-another-long-random-password/$database_pass/" .env.example > .env
  printf 'Created .env with random passwords. Your login is ADMIN_USERNAME / ADMIN_PASSWORD in that file.\n'
fi
docker compose up --build -d --wait --wait-timeout 300
bound_address=$(docker compose port api 8000)
bound_port=${bound_address##*:}
printf 'Adwatch is ready at http://localhost:%s\n' "$bound_port"
