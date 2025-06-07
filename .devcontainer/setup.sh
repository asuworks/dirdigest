#!/bin/bash
set -e

echo "Setting up the development environment..."

# Source ASDF to ensure uv is on the path and configured.
# This is good practice for consistency.
. "$HOME/.asdf/asdf.sh"

echo "Installing dependencies with 'uv sync'..."
# This will also create the .venv if it doesn't exist.
uv sync --all-extras

echo "Activating the virtual environment to run pre-commit..."

# This is the key fix: Source the BASH activation script.
# This adds .venv/bin to the script's PATH.
source .venv/bin/activate

# Now that the venv is active, the shell can find 'pre-commit' directly.
# We no longer need `uv run`.
pre-commit install --install-hooks

echo "✅ Setup complete!"
