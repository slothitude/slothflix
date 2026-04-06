#!/bin/bash
set -e

# Ensure data directories exist and are writable
mkdir -p /app/data /downloads

# Start FastAPI via uvicorn
exec uvicorn slothflix.main:app --host 0.0.0.0 --port ${FLASK_PORT:-8180} --workers 1
