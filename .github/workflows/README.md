# GitHub Actions Workflows

This directory contains automated workflows for the Polako Finance Python SDK.

## Workflows

### 1. CI Workflow (`ci.yml`)

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches

**Jobs:**
- **Test**: Runs tests on Python 3.7-3.12
- **Lint**: Runs code quality checks (black, isort, flake8, mypy)
- **Build**: Builds the package and validates it

**Purpose:**
Ensures code quality and compatibility across Python versions before merging.

### 2. Publish Workflow (`publish.yml`)

**Triggers:**
- GitHub release is published → Publishes to **PyPI**
- Push to `develop` branch → Publishes to **TestPyPI**
- Manual trigger via GitHub Actions UI

**Jobs:**
- **Build and Publish**:
  1. Runs tests
  2. Builds package
  3. Validates with twine
  4. Publishes to PyPI (releases) or TestPyPI (develop)

**Purpose:**
- Automates publishing to PyPI for production releases
- Automates publishing to TestPyPI for develop branch testing

## Required Secrets

The following secrets must be configured in GitHub repository settings:

| Secret Name | Description | Required For |
|-------------|-------------|--------------|
| `PYPI_API_TOKEN` | PyPI API token for production releases | `publish.yml` (releases) |
| `TEST_PYPI_API_TOKEN` | TestPyPI API token for develop branch | `publish.yml` (develop) |

### Setting Up Secrets

#### 1. Get PyPI Tokens

**For PyPI (Production):**
1. Go to [PyPI Account Settings](https://pypi.org/manage/account/)
2. Scroll to "API tokens" → Click "Add API token"
3. Name: "GitHub Actions - polako-finance"
4. Scope: Project (select polako-finance) or Entire account
5. Copy the token (starts with `pypi-`)

**For TestPyPI (Testing):**
1. Go to [TestPyPI Account Settings](https://test.pypi.org/manage/account/)
2. Scroll to "API tokens" → Click "Add API token"
3. Name: "GitHub Actions - polako-finance (test)"
4. Scope: Entire account (project may not exist yet)
5. Copy the token (starts with `pypi-`)

#### 2. Add Secrets to GitHub

1. Go to repository **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add both secrets:
   - Name: `PYPI_API_TOKEN`, Value: Your PyPI token
   - Name: `TEST_PYPI_API_TOKEN`, Value: Your TestPyPI token

## Usage

### Running CI

CI runs automatically on every push and pull request. No manual action needed.

### Testing on Develop Branch

When you push to the `develop` branch, the package is automatically published to TestPyPI:

1. **Push to develop**:
   ```bash
   git push origin develop
   ```

2. **Workflow runs automatically**:
   - Builds package
   - Publishes to TestPyPI

3. **Test installation from TestPyPI**:
   ```bash
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ polako-finance
   ```

4. **Verify the package**:
   ```python
   from polako.sdk import PolakoClient
   print(PolakoClient.__version__)
   ```

### Publishing a Production Release

1. Update version in:
   - `pyproject.toml`
   - `src/polako/sdk/__init__.py`
   - `CHANGELOG.md`

2. Commit and push changes

3. Create and push a git tag:
   ```bash
   git tag -a v0.2.0 -m "Release version 0.2.0"
   git push origin v0.2.0
   ```

4. Create a GitHub Release:
   - Go to **Releases** → **Draft a new release**
   - Select the tag
   - Add release notes
   - Click **Publish release**

5. The publish workflow will run automatically

### Manual Publishing

To manually trigger publishing:

1. Go to **Actions** tab
2. Select **Publish to PyPI**
3. Click **Run workflow**
4. Select branch and confirm

## Monitoring

- View workflow runs in the **Actions** tab
- Check logs for any failures
- Verify package on PyPI after successful publish

## Troubleshooting

### Workflow Fails

1. Check the workflow logs in the Actions tab
2. Common issues:
   - Missing or invalid `PYPI_API_TOKEN`
   - Test failures
   - Version already exists on PyPI
   - Build errors

### Re-running Failed Workflows

1. Go to the failed workflow run
2. Click **Re-run jobs** → **Re-run failed jobs**

### Skipping CI

To skip CI on a commit (use sparingly):

```bash
git commit -m "docs: update README [skip ci]"
```

## Best Practices

1. **Always test locally** before pushing
2. **Review CI results** before merging PRs
3. **Use semantic versioning** for releases
4. **Update CHANGELOG** before releasing
5. **Test on TestPyPI** before production release
