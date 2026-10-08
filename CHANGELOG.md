# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.9] - 2026-06-01

### Changed
- Version and README alignment for the 0.1.8 content.
- `_order.py` order-status surface extended.

## [0.1.8] - 2026-06-01

### Added
- `MerchantInfo` in the payment callback models.

### Changed
- **Breaking:** Python 3.9 support dropped, the package now requires Python >= 3.10.

### Security
- Patched 7 Dependabot alerts (h2, black, idna, pytest, filelock, virtualenv).

## [0.1.7] - 2026-05-23

### Added
- `check_order_status()` for querying the status of a payment session.
- `refund_session()` for full and partial refunds.
- Both methods use HMAC-SHA256 signature authentication.

## [0.1.6] - 2026-05-16

### Added
- Refunded items and amounts are exposed in `PaymentCallback`.

## [0.1.5] - 2026-05-15

### Added
- Support for the `generic_signed` callback format (schema 1.1) in `parse_payment_callback`.

## [0.1.4] - 2026-05-11

### Changed
- All endpoints now use the `/v1/` API prefix.
- SDK base URLs updated to the new `api.infra` hostnames.

## [0.1.3] - 2026-03-28

### Added
- `get_session_details()` for retrieving payment session info.

## [0.1.2] - 2026-03-22

### Added
- `get_payment_url()` for initiating payment on an existing session.

## [0.1.1] - 2025-11-02

### Added
- Initial public release: async client (httpx), HMAC-SHA256 signed `create_order`, payment callback parsing, PyPI publishing.

[Unreleased]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.9...HEAD
[0.1.9]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.8...release-v0.1.9
[0.1.8]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.7...release-v0.1.8
[0.1.7]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.6...release-v0.1.7
[0.1.6]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.5...release-v0.1.6
[0.1.5]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.4...release-v0.1.5
[0.1.4]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.3...release-v0.1.4
[0.1.3]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.2...release-v0.1.3
[0.1.2]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.1...release-v0.1.2
[0.1.1]: https://github.com/Polako-Finance/python-sdk/releases/tag/release-v0.1.1
