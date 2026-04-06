#!/bin/bash
set -e
# Ensure data dirs are writable (Docker named volumes mount as root)
mkdir -p /app/data /downloads
chown -R slothflix:slothflix /app/data /downloads 2>/dev/null || true
exec gosu slothflix uvicorn slothflix.main:app --host 0.0.0.0 --port ${FLASK_PORT:-8180} --workers 1
