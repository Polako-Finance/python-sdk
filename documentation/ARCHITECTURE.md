# python-sdk — Architecture

> **Platform context**: [Service Catalog](../../documentation/target-state/service-catalog.md)

## Role

Public Python SDK (`polako-finance` on PyPI) for merchant payment integrations. Async-first, HMAC-SHA256 signed.

## Operations

- Create payment orders (POST /v1/session/signed)
- Get session details, payment URLs, order status; full and partial refunds
- Parse/verify payment callbacks
- Subscriptions: create a subscription (POST /v1/company/{company_id}/subscriptions) and get the 3DS registration form;
  verify and read the subscription webhooks and the registration-failure notification
  (contract, merchant example and interface: [SUBSCRIPTIONS-SPEC.md](SUBSCRIPTIONS-SPEC.md))

## Modules

All under `src/polako/sdk/`; the package exports its public names from `__init__.py`.

| Module | Role |
|--------|------|
| `_async_api.py` | `AsyncPolakoClient` (exported as `PolakoClient`): the payment methods, `create_subscription`, `parse_payment_callback` |
| `_async_client.py` | The HTTP transport: headers, (de)serialization, mapping of statuses to exceptions, retries of requests that carry an `Idempotency-Key` |
| `_exceptions.py` | Exceptions: by HTTP status, configuration, webhook signature and payload |
| `_serializable.py` | Dataclass (de)serialization with wire aliases (`alias` metadata) and a decode hook |
| `_order.py` | Payment models |
| `_subscription.py` | The subscription request and response, the three registration forms, `SubscriptionCreated` |
| `_webhook.py` | Signature verification, the subscription events, the registration-failure notification |
| `_constants.py` | Currencies, languages, tax schemas, `BillingInterval`, base URLs |

## Quality Checks

Three independent checks, each with its own entry point and none depending on the others:

| Check | Where | What it covers |
|-------|-------|----------------|
| Tests | `tests/` (a separate Poetry project with its own `pyproject.toml` and lock file), `make test` / `make test-cov` (coverage of `polako.sdk`) | SDK behaviour against a fake gateway: `conftest.py` patches `httpx.AsyncClient` with `httpx.MockTransport` and records every request |
| Lint and types | `make lint`, `make type-check` | black, isort, flake8 on `src/` and `tests/`; mypy on `src/` |
| Documentation check | `scripts/check_docs.py`, `make check-docs`, CI job `docs` | Python blocks in `README.md`, `README.pypi.md`, `examples/README.md` |

### Tests

`tests/` is a separate Poetry project (own `pyproject.toml` and `poetry.lock`, see DECISIONS #7). It installs the SDK
from the repository root in editable mode and adds pytest, pytest-asyncio and pytest-cov. The SDK's `pyproject.toml`
lists no test dependencies, and building the SDK never touches `tests/`: the wheel holds only `polako/`, the source
distribution excludes `tests/`. The tests stay in the repository for anyone who wants to read how the SDK is used.

- **Data:** `generators.py` makes random values, `factories.py` builds valid objects and gateway payloads with
  `make_*(**overrides)` (DECISIONS #12). Signatures in the tests are computed by code written out in the tests, not by the SDK.
- **Fake gateway:** the `gateway` fixture in `conftest.py` records every request and answers from a per-test script,
  including exceptions for network failures; the `sleeps` fixture replaces the wait between retries.
- **Run:** `poetry -C tests run pytest` (or `make test`). CI runs the job `test` on Python 3.10, 3.11, 3.12 and 3.13.
- **End-to-end tests** (`tests/integration/`, DECISIONS #14) run the whole subscription chain over real HTTP on the
  loopback interface, with two local `aiohttp` servers on free ports:
  - `gateway_test_server.py`, an emulator of the gateway. It models what the gateway is documented to do for
    subscriptions: the subscribe endpoint with its checks in the gateway's order (validation, then the platform API key,
    then the service rules), idempotency replay, the three kinds of registration form, a rate limit with `Retry-After`,
    planned outages, dropped connections and card-processor refusals; and the other direction: lifecycle webhooks and the
    registration-failure notification, signed and retried the way the gateway does it (compact JSON with sorted keys,
    HMAC-SHA256 under the platform API key, three attempts for 5xx and network errors, 4xx final; one attempt for the
    registration failure, which is unsigned for a subscription made without a platform). Every request and delivery is
    recorded. It is a model written from the contract, so it cannot show where the real gateway differs.
  - `merchant_receiver.py`, a merchant's endpoint written the way the documentation tells a merchant to write it: it
    reads the raw body and passes it to the SDK. It can also play a merchant who serializes the JSON again, one whose
    endpoint is failing, and one who accepts unsigned notifications.
  The SDK is pointed at the emulator by replacing the test base URL for the length of a test (the `gateway_server`
  fixture); no production code has a hook for tests. Waits between retries are replaced and the emulator's clock is
  injectable, so no test sleeps. The fake-gateway tests stay for failures that are hard to produce over a socket.

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
