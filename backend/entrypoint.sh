#!/bin/bash
set -e

# Use the venv directly — uv run re-resolves build deps which
# requires network access to PyPI. The venv is fully built at
# image build time so we just need to activate and run.
export PATH="/app/.venv/bin:$PATH"

echo "Running database migrations..."
python -m alembic upgrade head

echo "Starting Parry backend..."
exec "$@"
