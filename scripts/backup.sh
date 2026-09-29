#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p work/backups
backup="work/backups/adwatch-$(date -u +%Y%m%dT%H%M%SZ).sql"
umask 077
docker compose exec -T db pg_dump -U adwatch --clean --if-exists adwatch > "$backup"
printf 'Backup saved to %s\n' "$backup"
