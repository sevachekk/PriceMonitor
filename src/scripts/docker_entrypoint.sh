#!/bin/sh
set -eu

python /app/src/scripts/bootstrap_runtime.py
exec "$@"
