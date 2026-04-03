# python-sdk — Architecture

> **Platform context**: [Service Catalog](../../documentation/target-state/service-catalog.md)

## Role

Public Python SDK (`polako-finance` on PyPI) for merchant payment integrations. Async-first, HMAC-SHA256 signed.

## Operations

- Create payment orders (POST /api/session/signed)
- Get session details, payment URLs
- Parse/verify payment callbacks

## Migration Impact

Minimal — SDK targets payment-gateway endpoints which are NOT being extracted.

## Key Configuration

- PyPI: `polako-finance` v0.1.3
- Python: 3.9+
- Dependency: httpx[http2]
- Currencies: RSD | Languages: sr, en, ru
