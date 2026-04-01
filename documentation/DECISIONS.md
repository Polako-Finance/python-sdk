# python-sdk — Decisions Log

> **Platform decisions**: [Service Catalog](../../documentation/architecture/service-catalog.md)

| # | Decision | Rationale | Date | Platform Impact |
|---|----------|-----------|------|-----------------|
| 1 | HMAC-SHA256 signature auth | No bearer tokens for merchant API; symmetric key signing | 2026 | No — SDK-scoped |
| 2 | Async-first (httpx) | Modern Python best practice | 2026 | No — SDK-scoped |
