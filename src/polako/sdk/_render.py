"""Rendering of the registration form the gateway returns into a page the customer's browser can follow."""

import html
from typing import Any, List
from urllib.parse import urlparse

from polako.sdk._subscription import FormPost, HppFormPost, RedirectForm, RegistrationForm

FORM_ID = "polako-registration"

# The names of the hidden inputs the card processor expects for a `form_post` form, with the field of the model that
# fills each one. They differ from the names in the gateway's response.
_FORM_POST_INPUTS = (
    ("Version", "version"),
    ("MerchantID", "merchant_id"),
    ("TerminalID", "terminal_id"),
    ("TotalAmount", "total_amount"),
    ("Currency", "currency"),
    ("Locale", "locale"),
    ("PurchaseTime", "purchase_time"),
    ("OrderID", "order_id"),
    ("Signature", "signature"),
)

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Continuing to the card registration</title>
{head}</head>
<body>
{body}</body>
</html>
"""


def render_registration_form(form: RegistrationForm, *, auto_submit: bool = True) -> str:
    """
    Turn the registration form of a new subscription into a page that sends the customer through the card registration.

    Return the result from your endpoint as an HTML response. For a ``FormPost`` or an ``HppFormPost`` the page holds
    a form with hidden fields that posts itself to the card processor; for a ``RedirectForm`` it redirects to the
    address. Every value is escaped, the address must be http or https, and the page loads nothing from elsewhere.

    Args:
        form: The ``registration_form`` of the ``SubscriptionCreated`` returned by ``create_subscription``
        auto_submit: Send the customer on at once (default). Posted forms do it with one small script and show a button
            when scripts are off; if your site forbids inline scripts, pass False and the customer presses the button.
            A redirect does it with a ``refresh`` header of the page and always shows a link.

    Raises:
        TypeError: If ``form`` is not a registration form
        ValueError: If the address of the form is not an http or https URL
    """
    if isinstance(form, FormPost):
        fields = [(name, getattr(form, attribute)) for name, attribute in _FORM_POST_INPUTS]
        fields[0] = ("Version", form.version or "1")
        return _form_page(form.action, fields, auto_submit)
    if isinstance(form, HppFormPost):
        return _form_page(form.action, list(form.fields.items()), auto_submit)
    if isinstance(form, RedirectForm):
        return _redirect_page(form.action, auto_submit)
    raise TypeError(f"expected a registration form, got {type(form).__name__}")


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _checked_address(action: Any) -> str:
    """The address, escaped, if it is an http or https URL; anything else (a script, a relative path) is refused.

    Spaces and control characters are refused too: a real address has none, and browsers drop some of them while
    reading a URL, which is how a scheme filter is usually got around.
    """
    parsed = urlparse(action) if isinstance(action, str) else None
    if (
        parsed is None
        or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in action)
        or parsed.scheme not in ("http", "https")
        or not parsed.netloc
    ):
        raise ValueError("the registration address must be an http or https URL")
    return _escape(action)


def _form_page(action: str, fields: List[Any], auto_submit: bool) -> str:
    target = _checked_address(action)
    inputs = "".join(f'<input type="hidden" name="{_escape(name)}" value="{_escape(value)}">\n' for name, value in fields)
    button = '<button type="submit">Continue</button>'
    script = ""
    if auto_submit:
        button = f"<noscript>{button}</noscript>"
        # The method of the element type itself: a provider field named "submit" would shadow the form's own.
        script = f'<script>HTMLFormElement.prototype.submit.call(document.getElementById("{FORM_ID}"));</script>\n'
    body = (
        "<p>Continuing to the card registration.</p>\n"
        f'<form id="{FORM_ID}" method="post" action="{target}">\n{inputs}{button}\n</form>\n{script}'
    )
    return _PAGE.format(head="", body=body)


def _redirect_page(action: str, auto_submit: bool) -> str:
    target = _checked_address(action)
    head = f'<meta http-equiv="refresh" content="0; url={target}">\n' if auto_submit else ""
    body = f'<p><a href="{target}">Continue to the card registration</a></p>\n'
    return _PAGE.format(head=head, body=body)
