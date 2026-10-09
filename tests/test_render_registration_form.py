"""render_registration_form: a page the customer's browser follows to the card registration."""

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

import pytest

import polako.sdk as sdk
from polako.sdk import FormPost, HppFormPost, RedirectForm, render_registration_form
from polako.sdk._subscription import parse_registration_form
from tests.factories import make_form_post_response, make_hpp_form_response, make_redirect_form_response
from tests.generators import generate_random_url, generate_readable_string

# The names the card processor expects for the form_post fields: attribute of the model -> name of the input.
FORM_POST_INPUTS = [
    ("version", "Version"),
    ("merchant_id", "MerchantID"),
    ("terminal_id", "TerminalID"),
    ("total_amount", "TotalAmount"),
    ("currency", "Currency"),
    ("locale", "Locale"),
    ("purchase_time", "PurchaseTime"),
    ("order_id", "OrderID"),
    ("signature", "Signature"),
]
HOSTILE = "\"><script>alert(1)</script>'&amp;<img src=x onerror=alert(1)>"


class Page(HTMLParser):
    """What a browser would find in the page."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: List[Dict[str, Optional[str]]] = []
        self.inputs: List[Tuple[str, str, str]] = []  # (type, name, value)
        self.links: List[str] = []
        self.metas: List[Dict[str, Optional[str]]] = []
        self.scripts: List[str] = []
        self.buttons: List[Tuple[bool, str]] = []  # (inside noscript, type)
        self._noscript = 0
        self._in_script = False
        self.attribute_names: List[str] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        self.attribute_names += [name for name, _ in attrs]
        if tag == "form":
            self.forms.append(data)
        elif tag == "input":
            self.inputs.append((data.get("type") or "", data.get("name") or "", data.get("value") or ""))
        elif tag == "a":
            self.links.append(data.get("href") or "")
        elif tag == "meta":
            self.metas.append(data)
        elif tag == "script":
            self._in_script = True
            self.scripts.append("")
        elif tag == "noscript":
            self._noscript += 1
        elif tag == "button":
            self.buttons.append((self._noscript > 0, data.get("type") or ""))

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False
        elif tag == "noscript":
            self._noscript -= 1

    def handle_data(self, data):
        if self._in_script:
            self.scripts[-1] += data


def form_of(make_response, **overrides):
    return parse_registration_form(make_response(**overrides))


def page(form, **kwargs) -> Page:
    return Page(render_registration_form(form, **kwargs))


def test_a_form_post_becomes_a_post_form_with_the_names_the_processor_expects():
    raw = make_form_post_response()
    form = parse_registration_form(raw)

    result = page(form)

    [html_form] = result.forms
    assert html_form["method"].lower() == "post"
    assert html_form["action"] == form.action
    assert {(kind, name) for kind, name, _ in result.inputs} == {("hidden", name) for _, name in FORM_POST_INPUTS}
    assert len(result.inputs) == len(FORM_POST_INPUTS)
    values = {name: value for _, name, value in result.inputs}
    for attribute, name in FORM_POST_INPUTS:
        assert values[name] == getattr(form, attribute), name


def test_an_empty_version_is_sent_as_one():
    form = form_of(make_form_post_response, version="")

    values = {name: value for _, name, value in page(form).inputs}

    assert values["Version"] == "1"


def test_a_form_post_keeps_a_version_it_was_given():
    form = form_of(make_form_post_response, version="2")

    assert {name: value for _, name, value in page(form).inputs}["Version"] == "2"


def test_an_hpp_form_passes_the_provider_fields_through_unchanged_and_in_order():
    raw = make_hpp_form_response()
    form = parse_registration_form(raw)

    result = page(form)

    [html_form] = result.forms
    assert html_form["method"].lower() == "post"
    assert html_form["action"] == form.action
    assert [(kind, name, value) for kind, name, value in result.inputs] == [
        ("hidden", name, value) for name, value in raw["fields"].items()
    ]


def test_an_hpp_form_without_fields_is_still_a_form():
    form = form_of(make_hpp_form_response, fields={})

    result = page(form)

    assert len(result.forms) == 1 and result.inputs == []


def test_a_missing_value_is_an_empty_input():
    form = HppFormPost(action=generate_random_url(), fields={"token": None})  # type: ignore[dict-item]

    assert page(form).inputs == [("hidden", "token", "")]


def test_a_redirect_form_is_a_link_not_a_form():
    form = form_of(make_redirect_form_response)

    result = page(form)

    assert result.forms == [] and result.inputs == []
    assert result.links == [form.action]


def test_a_redirect_form_redirects_on_its_own_when_asked_to():
    form = form_of(make_redirect_form_response)

    refresh = [m for m in page(form, auto_submit=True).metas if (m.get("http-equiv") or "").lower() == "refresh"]
    waiting = [m for m in page(form, auto_submit=False).metas if (m.get("http-equiv") or "").lower() == "refresh"]

    assert len(refresh) == 1
    assert refresh[0]["content"] == f"0; url={form.action}"
    assert waiting == []


@pytest.mark.parametrize("make_response", [make_form_post_response, make_hpp_form_response])
def test_a_posted_form_submits_itself_and_has_a_button_when_scripts_are_off(make_response):
    result = page(form_of(make_response), auto_submit=True)

    assert len(result.scripts) == 1
    assert result.forms[0]["id"] in result.scripts[0] and "HTMLFormElement.prototype.submit.call(" in result.scripts[0]
    assert result.buttons == [(True, "submit")]


FORM_PROPERTY_NAMES = ["submit", "action", "method", "id", "name", "target", "elements", "length"]


@pytest.mark.parametrize("field_name", FORM_PROPERTY_NAMES)
def test_a_provider_field_named_like_a_form_property_cannot_stop_the_page_from_submitting(field_name):
    """A field named `submit` replaces the form's submit method for the page's script (`form.submit` becomes the
    field), so the script calls the method of the form element type itself."""
    form = form_of(
        make_hpp_form_response, fields={field_name: generate_readable_string(6), "token": generate_readable_string(8)}
    )

    result = page(form, auto_submit=True)

    [script] = result.scripts
    assert "HTMLFormElement.prototype.submit.call(" in script
    assert ").submit()" not in script
    assert field_name in {name for _, name, _ in result.inputs}


@pytest.mark.parametrize("make_response", [make_form_post_response, make_hpp_form_response])
def test_a_posted_form_waits_for_a_click_when_it_is_not_to_submit_itself(make_response):
    result = page(form_of(make_response), auto_submit=False)

    assert result.scripts == []
    assert result.buttons == [(False, "submit")]


@pytest.mark.parametrize("make_response", [make_form_post_response, make_hpp_form_response, make_redirect_form_response])
def test_the_script_never_contains_data_from_the_form(make_response):
    result = page(form_of(make_response), auto_submit=True)

    assert all(re.fullmatch(r"[\w\s.()\"'=;,\-#]*", script) for script in result.scripts)


def test_values_names_and_addresses_are_escaped_so_the_browser_reads_back_what_was_given():
    action = "https://pay.example.com/enter?a=1&b=\"2\"&c='3'"
    fields = {HOSTILE: HOSTILE, "plain": HOSTILE + generate_readable_string(6)}
    form = HppFormPost(action=action, fields=fields)

    html = render_registration_form(form)
    result = Page(html)

    assert result.forms[0]["action"] == action
    assert [(name, value) for _, name, value in result.inputs] == list(fields.items())
    assert HOSTILE not in html
    assert action not in html
    assert len(result.scripts) == 1


def test_hostile_values_do_not_add_scripts_attributes_or_elements():
    form = HppFormPost(action=generate_random_url(), fields={"a": HOSTILE, HOSTILE: "b"})

    result = page(form, auto_submit=True)

    assert len(result.scripts) == 1
    assert "onerror" not in result.attribute_names
    assert result.links == []


def test_a_redirect_address_is_escaped_in_the_link_and_in_the_refresh():
    action = 'https://pay.example.com/go?a=1&b="2"&c=<x>'
    form = RedirectForm(action=action)

    result = page(form, auto_submit=True)

    assert result.links == [action]
    assert result.metas[-1]["content"] == f"0; url={action}"


@pytest.mark.parametrize(
    "action",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "ftp://pay.example.com/enter",
        "//pay.example.com/enter",
        "/enter",
        "pay.example.com/enter",
        "https://",
        "http://",
        "",
        "   ",
        " https://pay.example.com/enter",
        "https://pay.example.com/enter ",
        "https://pay.example.com/a b",
        "https://pay.example.com/en\nter",
        "https://pay.example.com/en\tter",
        "htt\tps://pay.example.com/enter",
        "\x00https://pay.example.com/enter",
        "https://pay.example.com/enter\x7f",
    ],
)
@pytest.mark.parametrize("make_form", [FormPost, HppFormPost, RedirectForm])
def test_an_address_that_is_not_http_or_https_is_refused(make_form, action):
    form = {
        FormPost: lambda: parse_registration_form(make_form_post_response(action=action)),
        HppFormPost: lambda: parse_registration_form(make_hpp_form_response(action=action)),
        RedirectForm: lambda: parse_registration_form(make_redirect_form_response(action=action)),
    }[make_form]()

    with pytest.raises(ValueError, match="http"):
        render_registration_form(form)


@pytest.mark.parametrize("action", ["http://pay.example.com/enter", "https://pay.example.com:8443/enter?x=1"])
def test_http_and_https_addresses_are_accepted(action):
    assert page(HppFormPost(action=action, fields={})).forms[0]["action"] == action


@pytest.mark.parametrize("not_a_form", [None, "https://pay.example.com", {"action": "https://pay.example.com"}, 7])
def test_anything_that_is_not_a_registration_form_is_a_type_error(not_a_form):
    with pytest.raises(TypeError):
        render_registration_form(not_a_form)  # type: ignore[arg-type]


@pytest.mark.parametrize("make_response", [make_form_post_response, make_hpp_form_response, make_redirect_form_response])
def test_the_result_is_a_complete_page_that_loads_nothing_from_elsewhere(make_response):
    html = render_registration_form(form_of(make_response))
    result = Page(html)

    assert html.lstrip().lower().startswith("<!doctype html>")
    assert any((m.get("charset") or "").lower() == "utf-8" for m in result.metas)
    assert "src" not in result.attribute_names
    assert "<link" not in html.lower() and "<img" not in html.lower() and "<iframe" not in html.lower()


@pytest.mark.parametrize("make_response", [make_form_post_response, make_hpp_form_response, make_redirect_form_response])
def test_the_same_form_gives_the_same_page(make_response):
    form = form_of(make_response)

    assert render_registration_form(form) == render_registration_form(form)


def test_auto_submit_is_on_by_default():
    form = form_of(make_hpp_form_response)

    assert render_registration_form(form) == render_registration_form(form, auto_submit=True)
    assert render_registration_form(form) != render_registration_form(form, auto_submit=False)


def test_auto_submit_can_only_be_given_by_keyword():
    with pytest.raises(TypeError):
        render_registration_form(form_of(make_hpp_form_response), False)  # type: ignore[misc]


def test_the_helper_is_part_of_the_public_api():
    assert "render_registration_form" in sdk.__all__
