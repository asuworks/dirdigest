#!/bin/bash
set -e

echo "Setting up the development environment..."

# Always start fresh in a dev container
echo "Removing old virtual environment if it exists..."
rm -rf .venv

# Source ASDF to make its shims available to this script.
# This ensures uv finds the correct python interpreter.
. "$HOME/.asdf/asdf.sh"

echo "Creating the virtual environment with 'uv'..."
# uv will automatically find and use the python from asdf
uv venv

echo "Installing dependencies into the virtual environment..."
# uv will automatically find and install into ./.venv
uv pip install -e .[dev]

echo "✅ Setup complete!"
