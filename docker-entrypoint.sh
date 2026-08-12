#!/bin/sh
set -e

# Railway mounts volumes as root. Fix ownership so the comply user can write.
chown -R comply:comply /app/data

# Drop privileges to comply user and exec the server (gosu forwards signals correctly)
exec gosu comply python -m uvicorn crp_comply.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8400}"
