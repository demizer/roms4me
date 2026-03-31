# roms4me task runner

# Default recipe - show available commands
default:
    @just --list

# Start the dev server with auto-reload
dev:
    @echo "roms4me dev server starting..."
    @echo "  → Mode:    development (reload enabled)"
    @echo ""
    uv run uvicorn roms4me.app:create_app --factory --reload

# Start the production server
serve:
    uv run roms4me

# Build and serve docs with live reload
docs: _ensure-deps
    @echo "Starting MkDocs development server with hot reload..."
    @echo "Documentation will be available at http://127.0.0.1:8001"
    uv run --group dev mkdocs serve --livereload --watch-theme

# Build docs for deployment
docs-build: _ensure-deps
    @echo "Building documentation..."
    uv run --group dev mkdocs build

# Deploy documentation to GitHub Pages
docs-deploy: _ensure-deps
    @echo "Deploying documentation to GitHub Pages..."
    uv run --group dev mkdocs gh-deploy

# Run type checking
typecheck:
    uv run pyright src/

# Format code
fmt:
    @echo "Formatting source files..."
    uv run ruff format src/

# Check formatting without modifying files
fmt-check:
    @echo "Checking source file formatting..."
    uv run ruff format --check src/

# Run tests
test:
    uv run pytest

# Run tests with browser visible
test-headed:
    uv run pytest --headed

# Lint code
lint:
    uv run ruff check src/

# Generate a new alembic migration (provide a message)
migrate-generate message:
    uv run alembic revision --autogenerate -m "{{message}}"

# Run database migrations to latest
migrate:
    uv run alembic upgrade head

# Reset the database (delete and recreate on next start)
db-reset:
    uv run roms4me db-reset

# Show current migration status
migrate-status:
    uv run alembic current

# Run audit checks using pre-commit on all files
audit:
    #!/usr/bin/env bash
    set -e

    # Colors
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'

    echo -e "${YELLOW}Running code audit with pre-commit...${NC}"
    echo ""

    # Check if pre-commit is installed
    if ! command -v pre-commit &> /dev/null; then
        echo -e "${YELLOW}pre-commit not found, attempting to install with uv...${NC}"

        # Check if uv is installed
        if ! command -v uv &> /dev/null; then
            echo -e "${RED}✗ Neither pre-commit nor uv is installed${NC}"
            echo ""
            echo "Please install one of the following:"
            echo "  1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
            echo "  2. Install pre-commit: pip install pre-commit"
            echo ""
            exit 1
        fi

        # Install pre-commit using uv
        echo "Installing pre-commit with uv..."
        uv tool install pre-commit
        echo -e "${GREEN}✓ pre-commit installed${NC}"
        echo ""
    fi

    # Run pre-commit on all files
    echo "Running pre-commit hooks on all files..."
    pre-commit run --all-files

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}✓ All audit checks passed!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════${NC}"

# Clean build artifacts
clean:
    @echo "Cleaning build artifacts..."
    rm -rf site/ dist/ .ruff_cache/

# Update uv lock file
uv-lock:
    @echo "Updating uv.lock..."
    uv lock

# Ensure dependencies are installed
_ensure-deps:
    #!/usr/bin/env bash
    set -e

    # Check if uv is installed
    if ! command -v uv &> /dev/null; then
        echo "Error: uv is not installed"
        echo "Please install uv: https://docs.astral.sh/uv/"
        exit 1
    fi

    # uv sync will create venv if needed and sync dependencies
    uv sync --quiet
