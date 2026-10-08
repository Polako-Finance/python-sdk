# python-sdk — Decisions Log

> **Platform decisions**: [Service Catalog](../../documentation/target-state/service-catalog.md)

| # | Decision | Rationale | Date | Platform Impact |
|---|----------|-----------|------|-----------------|
| 1 | HMAC-SHA256 signature auth | No bearer tokens for merchant API; symmetric key signing | 2026 | No — SDK-scoped |
| 2 | Async-first (httpx) | Modern Python best practice | 2026 | No — SDK-scoped |
| 3 | Documentation is written for the merchant and is the source of truth; it is never shaped by tests or tooling | A README/example must read as a merchant would write it (real values, no test-only placeholders, env vars or markers). Checks follow the docs, not the other way round | 2026-10-08 | No — SDK-scoped |
| 4 | Code blocks in the docs are verified by a separate static checker (`scripts/check_docs.py`), not by the test suite | Every python block is pinned by hash in `scripts/docs_manifest.json`; editing the docs makes the check fail, a developer reviews the change and accepts it with `python scripts/check_docs.py --update` (`make docs-update` is a shortcut). The check never executes the docs: it verifies syntax, `polako.sdk` imports and that calls fit the real signatures. Blocks with `...` arguments are treated as elided | 2026-10-08 | No — SDK-scoped |
| 5 | `create_order` defaults the language to Serbian (`sr`) through an explicit `DEFAULT_LANGUAGE` constant | The previous default was `next(iter(LANGUAGES))` over a set, so it could be `sr`, `en` or `ru` between interpreter runs. The currency default (`RSD`) is still taken from the one-element set | 2026-10-08 | Merchants that omit `language` now always get `sr` |
| 6 | Tests run the SDK against an in-process fake gateway (`httpx.MockTransport`), never against the network | Fast and deterministic; the `gateway` fixture patches the `httpx.AsyncClient` the SDK creates, so no production code needs a test hook | 2026-10-08 | No — SDK-scoped |
