#!/usr/bin/env bash
set -e

echo "Setting up dirdigest development environment..."

# Create virtual environment with uv
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv .venv
else
    echo "Virtual environment already exists."
fi

# Activate the virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Install dependencies using uv pip
echo "Installing dirdigest in editable mode with dev dependencies..."
uv pip install -e .[dev]

# Verify installation
echo "Verifying installation..."
dirdigest --version

echo "✅ Virtual environment created and dirdigest installed in editable mode."
echo "🎉 Setup complete! You can now run 'make test' to run the test suite."
