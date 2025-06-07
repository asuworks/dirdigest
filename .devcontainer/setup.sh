#!/bin/bash
set -e

echo "Setting up the development environment..."

# Always start fresh in a dev container
echo "Removing old virtual environment if it exists..."
rm -rf .venv

# Source ASDF to make its shims available to this script
# . "$HOME/.asdf/asdf.sh"

echo "Installing/updating dependencies with 'uv'..."
uv venv
source .venv/bin/activate.fish
uv pip install --editable .

echo "✅ Setup complete!"
