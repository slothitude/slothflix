#!/bin/bash
set -e
exec uvicorn slothflix.main:app --host 0.0.0.0 --port ${FLASK_PORT:-8180} --workers 1
