#!/usr/bin/fish
echo "Setting up the development environment..."

# Source ASDF to ensure uv is on the path and configured.
source ~/.asdf/asdf.fish

echo "Installing dependencies with 'uv sync'..."
# This will also create the .venv if it doesn't exist.
uv sync --all-extras

echo "Activating the virtual environment to run pre-commit..."

# This is the key fix: Source the FISH activation script.
# This adds .venv/bin to the script's PATH.
source .venv/bin/activate.fish

# Now that the venv is active, the shell can find 'pre-commit' directly.
# We no longer need `uv run`.
pre-commit install --install-hooks

echo "✅ Setup complete!"
