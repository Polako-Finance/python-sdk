"""The documentation check finds the python blocks of a markdown file and names each by its nearest real heading."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_docs.py"


@pytest.fixture(scope="module")
def check_docs():
    spec = importlib.util.spec_from_file_location("check_docs_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blocks_of(check_docs, monkeypatch, tmp_path, markdown: str):
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    path = tmp_path / "doc.md"
    path.write_text(markdown, encoding="utf-8")
    return [(key.split("::", 1)[1], code) for key, code in check_docs.extract_blocks(path)]


def test_a_python_block_is_named_by_the_heading_above_it(check_docs, monkeypatch, tmp_path):
    found = blocks_of(check_docs, monkeypatch, tmp_path, "## Setup\n\n```python\nx = 1\n```\n")

    assert found == [("Setup::0", "x = 1")]


def test_several_blocks_under_one_heading_are_numbered(check_docs, monkeypatch, tmp_path):
    found = blocks_of(
        check_docs, monkeypatch, tmp_path, "## A\n```python\none\n```\ntext\n```python\ntwo\n```\n## B\n```python\nthree\n```\n"
    )

    assert [name for name, _ in found] == ["A::0", "A::1", "B::0"]


@pytest.mark.parametrize("language", ["bash", "text", "sh", "shell", "console", "json", "yaml", ""])
def test_a_comment_line_in_another_kind_of_block_is_not_a_heading(check_docs, monkeypatch, tmp_path, language):
    markdown = f"## Setup\n\n```{language}\n# Install the package\npip install polako-finance\n```\n\n```python\nx = 1\n```\n"

    found = blocks_of(check_docs, monkeypatch, tmp_path, markdown)

    assert found == [("Setup::0", "x = 1")]


def test_a_comment_line_in_a_python_block_is_not_a_heading(check_docs, monkeypatch, tmp_path):
    markdown = "## Setup\n\n```python\n# A comment\nx = 1\n```\n\n```python\ny = 2\n```\n"

    found = blocks_of(check_docs, monkeypatch, tmp_path, markdown)

    assert found == [("Setup::0", "# A comment\nx = 1"), ("Setup::1", "y = 2")]


def test_a_tilde_fence_is_a_fence_too(check_docs, monkeypatch, tmp_path):
    markdown = "## Setup\n\n~~~bash\n# Install\n~~~\n\n```python\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Setup::0", "x = 1")]


def test_a_longer_fence_is_not_closed_by_a_shorter_one(check_docs, monkeypatch, tmp_path):
    markdown = "## Setup\n\n````markdown\n# Not a heading\n```python\nnot = 'a block'\n```\n````\n\n```python\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Setup::0", "x = 1")]


def test_a_real_heading_after_a_block_still_counts(check_docs, monkeypatch, tmp_path):
    markdown = "## One\n\n```bash\n# note\n```\n\n### Two\n\n```python\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Two::0", "x = 1")]


def test_a_block_that_is_never_closed_is_not_a_block(check_docs, monkeypatch, tmp_path):
    assert blocks_of(check_docs, monkeypatch, tmp_path, "## Setup\n\n```python\nx = 1\n") == []


def test_the_documentation_of_this_repository_names_its_blocks_by_real_headings(check_docs):
    """Every key of the manifest ends in a heading that exists in its file."""
    for key in check_docs.load_manifest():
        name, kind, _ = key.split("::")
        if kind == "file":
            continue
        text = (check_docs.ROOT / name).read_text(encoding="utf-8")
        assert any(line.lstrip("# ").strip() == kind and line.startswith("#") for line in text.splitlines()), key
