#!/usr/bin/fish

echo "Installing dependencies with 'uv sync'..."
# This will also create the .venv if it doesn't exist.
uv sync --all-extras

echo "Activating the virtual environment..."
source .venv/bin/activate.fish

echo "Activating pre-commit hooks..."
pre-commit install --install-hooks

echo "✅ Setup complete!"
