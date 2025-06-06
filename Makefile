.PHONY: help setup develop install-deps update-deps format lint mypy test validate docker-build docker-run docker-test clean configure-git activate-pre-commit

# Default target
help:
	@echo "Available commands:"
	@echo "  setup                 : Set up the development environment (install deps, pre-commit)."
	@echo "  develop               : Alias for 'install-deps' (install main and dev dependencies)."
	@echo "  install-deps          : Install main and dev dependencies using UV."
	@echo "  update-deps           : Update dependencies to the latest compatible versions."
	@echo "  format                : Format code with Ruff."
	@echo "  lint                  : Lint code with Ruff (with auto-fix)."
	@echo "  mypy                  : Run type checking with Mypy."
	@echo "  test                  : Run tests with Pytest."
	@echo "  validate              : Run all checks (format, lint, mypy, test)."
	@echo "  activate-pre-commit   : Install and activate pre-commit hooks."
	@echo "  clean                 : Clean up build artifacts and cache files."

# Setup the development environment
setup: install-deps activate-pre-commit
	@echo "Development environment ready."
	@echo "Run 'source .venv/bin/activate' to activate the virtual environment."

# Install development dependencies (main and dev)
develop: install-deps

# Install dependencies with UV, creates/updates uv.lock
# Using --cache-dir to keep UV's cache within the project for potentially better CI caching.
install-deps:
	uv sync --all-extras --cache-dir .uv_cache

update-deps:
	uv sync --all-extras --cache-dir .uv_cache
	@echo "Dependencies updated using 'uv sync'."

# Install and activate pre-commit hooks
activate-pre-commit:
	uv pip install pre-commit --cache-dir .uv_cache
	uv run pre-commit install

# Format code with Ruff
format:
	uv run ruff format .

# Lint code with Ruff (auto-fix enabled)
lint:
	uv run ruff check --fix .

# Type check with mypy
mypy:
	uv run mypy --package dirdigest --install-types --non-interactive

# Run tests with pytest
test:
	rm -rf tests/fixtures/test_dirs && bash tests/scripts/setup_test_dirs.sh && uv run pytest tests/ && rm -rf tests/fixtures/test_dirs

# Run format, lint, mypy and tests
validate: format lint mypy test

# Clean up build artifacts and cache files
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf ./*.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .mypy_cache/
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf .uv_cache/
	@echo "Cleaned project artifacts and caches."
