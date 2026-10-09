"""Smoke: the package imports and exposes what the README promises."""

import re
from importlib import metadata
from pathlib import Path

import polako.sdk as sdk


def test_all_exports_resolve():
    for name in sdk.__all__:
        assert hasattr(sdk, name), name


def test_version_matches_pyproject():
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    versions = re.findall(r'^version = "([^"]+)"', text, flags=re.MULTILINE)
    assert versions == [sdk.__version__, sdk.__version__]


def test_installed_metadata_version():
    assert metadata.version("polako-finance") == sdk.__version__


def test_exception_hierarchy():
    assert issubclass(sdk.HttpRequestError, sdk.HttpClientError)
