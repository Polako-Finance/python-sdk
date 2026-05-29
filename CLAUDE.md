# CLAUDE.md — python-sdk

This is the **python-sdk** — the public Python SDK (`polako-finance` on PyPI) for merchant payment integrations with the Polako Finance platform.

## Platform Context

This module is part of the **Polako Finance** platform.

- **Current state**: [../../documentation/current-state/architecture/overview.md](../../documentation/current-state/architecture/overview.md)
- **Target state**: [../../documentation/target-state/architecture/overview.md](../../documentation/target-state/architecture/overview.md)
- **Platform CLAUDE.md**: [../../CLAUDE.md](../../CLAUDE.md)
- **Module docs**: [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md) | [documentation/DECISIONS.md](documentation/DECISIONS.md) | [documentation/STATUS.md](documentation/STATUS.md)

## Common Commands

```bash
make install          # poetry install
make test             # pytest
make lint             # black, isort, flake8, mypy
make build            # poetry build
```

## Code Conventions

- **Python**: 3.9+ (broad compatibility for consumers)
- **Line length**: 128 characters
- **Formatting**: Black + isort (profile=black)
- **Type checking**: mypy (Python 3.11 target)
- **Async-first**: httpx with context manager pattern

## Key Context

- HMAC-SHA256 signature authentication (not Bearer tokens)
- Targets payment-gateway endpoints (minimal migration impact)
- Currencies: RSD | Languages: sr, en, ru
- PyPI package: `polako-finance` v0.1.6
