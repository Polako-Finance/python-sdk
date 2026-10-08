# python-sdk — Architecture

> **Platform context**: [Service Catalog](../../documentation/target-state/service-catalog.md)

## Role

Public Python SDK (`polako-finance` on PyPI) for merchant payment integrations. Async-first, HMAC-SHA256 signed.

## Operations

- Create payment orders (POST /v1/session/signed)
- Get session details, payment URLs
- Parse/verify payment callbacks

## Quality Checks

Three independent checks, each with its own entry point and none depending on the others:

| Check | Where | What it covers |
|-------|-------|----------------|
| Tests | `tests/`, `make test` / `make test-cov` (coverage of `polako.sdk`) | SDK behaviour against a fake gateway: `conftest.py` patches `httpx.AsyncClient` with `httpx.MockTransport` and records every request |
| Lint and types | `make lint`, `make type-check` | black, isort, flake8 on `src/` and `tests/`; mypy on `src/` |
| Documentation check | `scripts/check_docs.py`, `make check-docs`, CI job `docs` | Python blocks in `README.md`, `README.pypi.md`, `examples/README.md` |

### Documentation check

The documentation is written for merchants and is never adapted to tests or tooling (see DECISIONS #3, #4). The checker follows the docs:

1. Every python block is identified as `file::nearest heading::ordinal` and pinned by a hash in `scripts/docs_manifest.json`.
2. A new, changed or removed block fails the check. After reviewing the doc change, a developer runs `python scripts/check_docs.py --update` (or `make docs-update`); the manifest keeps the check kind (`static` or `skip`) of known blocks.
3. A `static` block is verified without running it: syntax, names imported from `polako.sdk`, and that calls to SDK classes and client methods fit their real signatures. Calls with `...`, `*args` or `**kwargs` are treated as elided.

## Migration Impact

Minimal — SDK targets payment-gateway endpoints which are NOT being extracted.

## Key Configuration

- PyPI: `polako-finance` v0.1.9
- Python: 3.10+ (CI matrix 3.10-3.13)
- Dependency: httpx[http2]
- Currencies: RSD | Languages: sr, en, ru
