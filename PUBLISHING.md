# Publishing Guide

This guide explains how to publish the Polako Finance Python SDK to PyPI.

## Prerequisites

1. **PyPI Account**: Create accounts on both [PyPI](https://pypi.org) and [TestPyPI](https://test.pypi.org)
2. **API Tokens**: Generate API tokens for both PyPI and TestPyPI
3. **Poetry**: Ensure Poetry is installed (`pip install poetry`)

## Pre-Publishing Checklist

Before publishing, ensure:

- [ ] All tests pass: `poetry run pytest`
- [ ] Code is formatted: `poetry run black src/`
- [ ] Imports are sorted: `poetry run isort src/`
- [ ] Type checking passes: `poetry run mypy src/`
- [ ] Linting passes: `poetry run flake8 src/`
- [ ] Version number is updated in:
  - [ ] `pyproject.toml`
  - [ ] `src/polako/sdk/__init__.py` (`__version__`)
  - [ ] `CHANGELOG.md`
- [ ] README.md is up to date
- [ ] CHANGELOG.md has entry for new version
- [ ] All dependencies are correctly specified

## Building the Package

### 1. Clean Previous Builds

```bash
rm -rf dist/ build/ *.egg-info
```

### 2. Build with Poetry

```bash
poetry build
```

This creates both `.tar.gz` (source) and `.whl` (wheel) distributions in the `dist/` directory.

### 3. Verify Build Contents

```bash
tar -tzf dist/polako-finance-*.tar.gz
unzip -l dist/polako_finance-*.whl
```

Ensure all necessary files are included:
- Source code (`src/polako/`)
- `py.typed` marker file
- `README.md`
- `LICENSE`
- `CHANGELOG.md`

## Publishing to TestPyPI (Recommended First)

Test your package on TestPyPI before publishing to the main PyPI.

### 1. Configure TestPyPI

Add TestPyPI repository to Poetry:

```bash
poetry config repositories.testpypi https://test.pypi.org/legacy/
```

### 2. Set API Token

```bash
poetry config pypi-token.testpypi <your-testpypi-token>
```

### 3. Publish to TestPyPI

```bash
poetry publish -r testpypi
```

### 4. Test Installation from TestPyPI

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ polako-finance
```

Note: `--extra-index-url` is needed because dependencies (like `httpx`) are on main PyPI.

### 5. Test the Installed Package

```python
from polako.sdk import PolakoClient
print(PolakoClient.__doc__)
```

## Publishing to PyPI (Production)

Once testing is complete:

### 1. Set PyPI API Token

```bash
poetry config pypi-token.pypi <your-pypi-token>
```

### 2. Publish to PyPI

```bash
poetry publish
```

### 3. Verify on PyPI

Visit https://pypi.org/project/polako-finance/ to verify the package.

### 4. Test Installation

```bash
pip install polako-finance
```

## Alternative: Using Twine

If you prefer using `twine` instead of Poetry:

### 1. Install Twine

```bash
pip install twine
```

### 2. Upload to TestPyPI

```bash
twine upload --repository testpypi dist/*
```

### 3. Upload to PyPI

```bash
twine upload dist/*
```

## Post-Publishing Steps

1. **Create Git Tag**:
   ```bash
   git tag -a v0.1.0 -m "Release version 0.1.0"
   git push origin v0.1.0
   ```

2. **Create GitHub Release**:
   - Go to GitHub repository
   - Click "Releases" → "Create a new release"
   - Select the tag you just created
   - Add release notes from CHANGELOG.md
   - Attach the distribution files from `dist/`

3. **Update Documentation**:
   - Update any external documentation
   - Announce the release on relevant channels

4. **Monitor**:
   - Check PyPI download statistics
   - Monitor GitHub issues for bug reports
   - Watch for user feedback

## Version Numbering

Follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (X.0.0): Incompatible API changes
- **MINOR** (0.X.0): New functionality, backwards compatible
- **PATCH** (0.0.X): Bug fixes, backwards compatible

Examples:
- `0.1.0` → `0.1.1`: Bug fix
- `0.1.1` → `0.2.0`: New feature
- `0.2.0` → `1.0.0`: Breaking changes

## Troubleshooting

### Package Already Exists

If you get an error that the package version already exists:
- You cannot overwrite a published version
- Increment the version number and rebuild

### Missing Files in Distribution

If files are missing:
- Check `MANIFEST.in`
- Verify `pyproject.toml` includes correct paths
- Rebuild the package

### Import Errors After Installation

If imports fail:
- Verify package structure in `dist/` files
- Check `pyproject.toml` `[tool.poetry]` packages configuration
- Ensure `__init__.py` files exist in all package directories

### Type Hints Not Working

If type hints aren't recognized:
- Ensure `py.typed` file exists in `src/polako/`
- Verify it's included in the distribution
- Check `MANIFEST.in` includes `py.typed`

## Security Best Practices

1. **Never commit API tokens** to version control
2. **Use environment variables** for sensitive data:
   ```bash
   export POETRY_PYPI_TOKEN_PYPI=<your-token>
   ```
3. **Enable 2FA** on your PyPI account
4. **Use scoped tokens** instead of username/password
5. **Rotate tokens** periodically

## Automated Publishing with GitHub Actions

The repository includes automated workflows for CI/CD:

### GitHub Actions Workflows

1. **`.github/workflows/ci.yml`** - Continuous Integration
   - Runs on every push and pull request
   - Tests on Python 3.7-3.12
   - Runs linting (black, isort, flake8, mypy)
   - Builds package to verify it's valid

2. **`.github/workflows/publish.yml`** - Automated Publishing
   - Triggers on GitHub releases
   - Can be manually triggered
   - Runs tests before publishing
   - Publishes to PyPI automatically

### Setting Up GitHub Actions

#### 1. Configure PyPI API Token

1. Go to [PyPI Account Settings](https://pypi.org/manage/account/)
2. Scroll to "API tokens"
3. Click "Add API token"
4. Name it (e.g., "GitHub Actions - polako-finance")
5. Set scope to "Entire account" or specific to this project
6. Copy the token (starts with `pypi-`)

#### 2. Add Secret to GitHub

1. Go to your GitHub repository
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `PYPI_API_TOKEN`
5. Value: Paste your PyPI token
6. Click **Add secret**

#### 3. Publishing a New Release

To publish a new version:

1. **Update version** in:
   - `pyproject.toml`
   - `src/polako/sdk/__init__.py`
   - `CHANGELOG.md`

2. **Commit and push** changes:
   ```bash
   git add .
   git commit -m "Bump version to 0.2.0"
   git push origin main
   ```

3. **Create and push tag**:
   ```bash
   git tag -a v0.2.0 -m "Release version 0.2.0"
   git push origin v0.2.0
   ```

4. **Create GitHub Release**:
   - Go to repository → **Releases** → **Draft a new release**
   - Choose the tag you just created (v0.2.0)
   - Title: `v0.2.0`
   - Description: Copy from CHANGELOG.md
   - Click **Publish release**

5. **Automated workflow runs**:
   - GitHub Actions will automatically:
     - Run all tests
     - Build the package
     - Publish to PyPI
   - Monitor progress in the **Actions** tab

#### 4. Manual Trigger (Optional)

You can also manually trigger publishing:

1. Go to **Actions** tab
2. Select **Publish to PyPI** workflow
3. Click **Run workflow**
4. Select branch
5. Click **Run workflow**

### Workflow Features

The publish workflow includes:
- ✅ Automated testing before publishing
- ✅ Package validation with twine
- ✅ Caching for faster builds
- ✅ Build artifact uploads
- ✅ Fail-safe: Won't publish if tests fail

## Resources

- [Poetry Documentation](https://python-poetry.org/docs/)
- [PyPI Help](https://pypi.org/help/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Semantic Versioning](https://semver.org/)
- [Keep a Changelog](https://keepachangelog.com/)
