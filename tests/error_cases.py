"""The failures the gateway answers with, and the exception the SDK raises for each.

One table for every test that checks how a status becomes an exception, so that a new status is added in one place.
Input that is wrong on the caller's side never reaches the gateway; it is a ``ValueError`` (or a ``ConfigurationError``)
raised before a request is made, and each call's tests check that separately.
"""

from polako.sdk import (
    ConflictError,
    ForbiddenError,
    HttpRequestError,
    NotFoundError,
    RateLimitedError,
    RequestValidationError,
    ServerError,
    UnauthorizedError,
)

# (HTTP status, the exact class raised). A status the SDK has no class of its own for stays a plain HttpRequestError;
# 400 is what the gateway answers to a filter or a sort field it does not accept.
STATUS_ERRORS = [
    (400, HttpRequestError),
    (401, UnauthorizedError),
    (403, ForbiddenError),
    (404, NotFoundError),
    (409, ConflictError),
    (410, HttpRequestError),
    (418, HttpRequestError),
    (422, RequestValidationError),
    (429, RateLimitedError),
    (500, ServerError),
    (502, ServerError),
    (503, ServerError),
]

# only the statuses that have a class of their own
SPECIFIC_STATUS_ERRORS = [(status, error) for status, error in STATUS_ERRORS if error is not HttpRequestError]
# the statuses that stay a plain HttpRequestError
PLAIN_STATUSES = [status for status, error in STATUS_ERRORS if error is HttpRequestError]
