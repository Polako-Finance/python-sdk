.PHONY: help install test lint format clean build publish version release

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)Polako Common Library - Available Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

install: ## Install dependencies
	@echo "$(BLUE)Installing dependencies...$(NC)"
	poetry install
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

install-dev: ## Install development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	poetry install --with dev
	poetry run pre-commit install
	@echo "$(GREEN)✓ Development environment ready$(NC)"

test: ## Run tests
	@echo "$(BLUE)Running tests...$(NC)"
	poetry run pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	poetry run pytest tests/ -v --cov=polako_common --cov-report=html --cov-report=term
	@echo "$(GREEN)✓ Coverage report generated in htmlcov/$(NC)"

test-watch: ## Run tests in watch mode
	@echo "$(BLUE)Running tests in watch mode...$(NC)"
	poetry run pytest-watch tests/ -v

lint: ## Run linters
	@echo "$(BLUE)Running linters...$(NC)"
	poetry run black --check src/ tests/
	poetry run isort --check-only src/ tests/
	poetry run flake8 src/ tests/
	@echo "$(GREEN)✓ Linting passed$(NC)"

format: ## Format code
	@echo "$(BLUE)Formatting code...$(NC)"
	poetry run black src/ tests/
	poetry run isort src/ tests/
	@echo "$(GREEN)✓ Code formatted$(NC)"

type-check: ## Run type checking
	@echo "$(BLUE)Running type checks...$(NC)"
	poetry run mypy src/
	@echo "$(GREEN)✓ Type checking passed$(NC)"

clean: ## Clean build artifacts
	@echo "$(BLUE)Cleaning build artifacts...$(NC)"
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✓ Cleaned$(NC)"

build: clean ## Build package
	@echo "$(BLUE)Building package...$(NC)"
	poetry build
	@echo "$(GREEN)✓ Package built in dist/$(NC)"

publish-test: build ## Publish to TestPyPI
	@echo "$(BLUE)Publishing to TestPyPI...$(NC)"
	poetry publish -r testpypi
	@echo "$(GREEN)✓ Published to TestPyPI$(NC)"

version: ## Show current version
	@echo "$(BLUE)Current version:$(NC) $(shell poetry version -s)"

release: ## Create GitHub release with current version
	@bash scripts/create_release.sh

release-patch: ## Bump patch version and create GitHub release (0.1.0 -> 0.1.1)
	@poetry version patch
	@bash scripts/create_release.sh

release-minor: ## Bump minor version and create GitHub release (0.1.0 -> 0.2.0)
	@poetry version minor
	@bash scripts/create_release.sh

release-major: ## Bump major version and create GitHub release (0.1.0 -> 1.0.0)
	@poetry version major
	@bash scripts/create_release.sh

check: lint test ## Run all checks (lint + test)
	@echo "$(GREEN)✓ All checks passed$(NC)"

pre-commit: ## Run pre-commit hooks on all files
	@echo "$(BLUE)Running pre-commit hooks...$(NC)"
	poetry run pre-commit run --all-files
	@echo "$(GREEN)✓ Pre-commit checks passed$(NC)"

update: ## Update dependencies
	@echo "$(BLUE)Updating dependencies...$(NC)"
	poetry update
	@echo "$(GREEN)✓ Dependencies updated$(NC)"

lock: ## Update poetry.lock
	@echo "$(BLUE)Updating poetry.lock...$(NC)"
	poetry lock --no-update
	@echo "$(GREEN)✓ poetry.lock updated$(NC)"

shell: ## Open poetry shell
	poetry shell

info: ## Show package info
	@echo "$(BLUE)Package Information$(NC)"
	@echo ""
	@poetry version
	@echo ""
	@echo "$(BLUE)Dependencies:$(NC)"
	@poetry show --tree --no-dev
	@echo ""
	@echo "$(BLUE)Development Dependencies:$(NC)"
	@poetry show --tree --only dev

contracts: ## List all contract schemas
	@echo "$(BLUE)Available Contract Schemas$(NC)"
	@echo ""
	@find src/polako_common/contracts -name "*.json" -type f | sort

validate-contracts: ## Validate all contract schemas
	@echo "$(BLUE)Validating contract schemas...$(NC)"
	@poetry run python -c "from polako_common.contracts import validate_all_contracts; validate_all_contracts()"
	@echo "$(GREEN)✓ All contracts valid$(NC)"
