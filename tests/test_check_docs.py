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


def test_a_line_with_backticks_and_text_after_them_is_not_a_fence(check_docs, monkeypatch, tmp_path):
    markdown = "## Setup\n\n```x``` is shown like this\n\n```python\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Setup::0", "x = 1")]


def test_a_tilde_fence_may_have_backticks_in_its_info_string(check_docs, monkeypatch, tmp_path):
    markdown = "## Setup\n\n~~~text `quoted`\n# Not a heading\n~~~\n\n```python\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Setup::0", "x = 1")]


@pytest.mark.parametrize("indent", [" ", "   ", "    ", "      ", "\t"])
def test_a_block_inside_a_list_is_found_and_dedented(check_docs, monkeypatch, tmp_path, indent):
    body = f"{indent}```python\n{indent}x = 1\n{indent}if x:\n{indent}    y = 2\n{indent}```\n"
    markdown = f"## Setup\n\n1. Do this:\n\n{body}\n```python\nz = 3\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [
        ("Setup::0", "x = 1\nif x:\n    y = 2"),
        ("Setup::1", "z = 3"),
    ]


def test_an_indented_block_is_closed_by_a_fence_with_any_indent(check_docs, monkeypatch, tmp_path):
    markdown = "## Setup\n\n- Step\n\n    ```python\n    x = 1\n```\n\n```python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Setup::0", "x = 1"), ("Setup::1", "y = 2")]


def test_a_real_heading_after_a_block_still_counts(check_docs, monkeypatch, tmp_path):
    markdown = "## One\n\n```bash\n# note\n```\n\n### Two\n\n```python\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Two::0", "x = 1")]


@pytest.mark.parametrize("language", ["python", "bash", ""])
def test_a_block_that_is_never_closed_is_an_error_naming_its_line(check_docs, monkeypatch, tmp_path, language):
    """It would swallow the rest of the file, so the blocks after it would silently go unchecked."""
    with pytest.raises(ValueError, match=r"line 3\b.*never closed"):
        blocks_of(check_docs, monkeypatch, tmp_path, f"## Setup\n\n```{language}\nx = 1\n\n```python\ny = 2\n~~~\n")


def test_the_check_fails_on_a_block_that_is_never_closed(check_docs, monkeypatch, tmp_path, capsys):
    (tmp_path / "doc.md").write_text("## Setup\n\n```python\nx = 1\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "DOCS", ["doc.md"])
    monkeypatch.setattr(check_docs, "MANIFEST", tmp_path / "manifest.json")

    assert check_docs.verify() == 1
    assert "never closed" in capsys.readouterr().out


@pytest.mark.parametrize("indent", ["    ", "      ", "\t"])
def test_an_indented_fence_outside_a_list_is_an_indented_code_block_and_not_a_fence(check_docs, monkeypatch, tmp_path, indent):
    body = f"{indent}```python\n{indent}x = 1\n{indent}```\n"
    markdown = f"## Setup\n\nA paragraph.\n\n{body}\n```python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Setup::0", "y = 2")]


@pytest.mark.parametrize("marker", ["-", "*", "+", "1.", "12)"])
def test_a_fence_in_a_list_item_is_a_fence_across_blank_lines_and_nested_text(check_docs, monkeypatch, tmp_path, marker):
    markdown = f"## Setup\n\n{marker} First step\n\n    More text of the item.\n\n    ```python\n    x = 1\n    ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("Setup::0", "x = 1")]


def test_a_fence_after_the_list_has_ended_is_not_a_fence(check_docs, monkeypatch, tmp_path):
    markdown = "## Setup\n\n- An item\n\nA paragraph ends the list.\n\n    ```python\n    x = 1\n    ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == []


def test_a_heading_ends_a_list(check_docs, monkeypatch, tmp_path):
    markdown = "- An item\n\n## Next\n\n    ```python\n    x = 1\n    ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == []


def test_the_documentation_of_this_repository_names_its_blocks_by_real_headings(check_docs):
    """Every key of the manifest ends in a heading that exists in its file."""
    for key in check_docs.load_manifest():
        name, kind, _ = key.split("::")
        if kind == "file":
            continue
        text = (check_docs.ROOT / name).read_text(encoding="utf-8")
        assert any(line.lstrip("# ").strip() == kind and line.startswith("#") for line in text.splitlines()), key


def test_a_line_of_backticks_indented_four_columns_inside_a_block_does_not_close_it(check_docs, monkeypatch, tmp_path):
    """Outside a list a closing fence has at most three spaces; this line is text of the block (nested markup)."""
    markdown = "## A\n\n```python\ntext = '''\n    ```\n'''\n```\n\n```python\ny = 2\n```\n"

    found = blocks_of(check_docs, monkeypatch, tmp_path, markdown)

    assert found == [("A::0", "text = '''\n    ```\n'''"), ("A::1", "y = 2")]


def test_a_fence_in_a_list_may_be_closed_three_columns_deeper_than_it_was_opened(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n- Step\n\n  ```python\n  x = 1\n     ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1")]


def test_the_indent_of_a_block_is_taken_off_by_columns_whatever_it_is_made_of(check_docs, monkeypatch, tmp_path):
    """The fence is indented with spaces and the body with tabs: four columns come off, the rest stays."""
    markdown = "## A\n\n- Step\n\n    ```python\n\tif x:\n\t\ty = 2\n    ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "if x:\n    y = 2")]


def test_a_body_line_indented_less_than_the_fence_loses_only_what_it_has(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n- Step\n\n      ```python\n   x = 1\n      ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1")]


def test_updating_the_manifest_reports_a_broken_document_and_writes_nothing(check_docs, monkeypatch, tmp_path, capsys):
    (tmp_path / "doc.md").write_text("## Setup\n\n```python\nx = 1\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "DOCS", ["doc.md"])
    monkeypatch.setattr(check_docs, "MANIFEST", manifest)

    assert check_docs.update() == 1
    assert "never closed" in capsys.readouterr().out
    assert not manifest.exists()


@pytest.mark.parametrize("info", ["python", "Python", "PYTHON", "py", "py3", "python3", "python title=setup", "python {1,3}"])
def test_the_language_of_a_fence_is_its_first_word_in_any_case(check_docs, monkeypatch, tmp_path, info):
    markdown = f"## A\n\n```{info}\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1")]


@pytest.mark.parametrize("info", ["pycon", "pythonic", "py2x", "bash", "text", ""])
def test_a_fence_in_another_language_is_not_a_python_block(check_docs, monkeypatch, tmp_path, info):
    markdown = f"## A\n\n```{info}\n>>> x = 1\n```\n\n```Python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "y = 2")]


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
def test_a_heading_indented_by_up_to_three_spaces_is_a_heading(check_docs, monkeypatch, tmp_path, indent):
    markdown = f"## A\n\n```python\nx = 1\n```\n\n{indent}## B\n\n```python\ny = 2\n```\n"

    assert [name for name, _ in blocks_of(check_docs, monkeypatch, tmp_path, markdown)] == ["A::0", "B::0"]


def test_a_heading_indented_four_spaces_is_code_and_not_a_heading(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n    ## B\n\n```python\nx = 1\n```\n"

    assert [name for name, _ in blocks_of(check_docs, monkeypatch, tmp_path, markdown)] == ["A::0"]


@pytest.mark.parametrize("quote", ["> ", "  > ", "> > "])
def test_a_block_inside_a_quote_is_found_without_the_quote_marks(check_docs, monkeypatch, tmp_path, quote):
    markdown = f"## A\n\n{quote}```python\n{quote}x = 1\n{quote}if x:\n{quote}    y = 2\n{quote}```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1\nif x:\n    y = 2")]


def test_a_quote_mark_without_a_space_after_it_is_read_too(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n>```python\n>x = 1\n>```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1")]


def test_a_block_in_a_quote_that_ends_before_the_block_does_is_an_error(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n> ```python\n> x = 1\n\n```python\ny = 2\n```\n"

    with pytest.raises(ValueError, match="never closed"):
        blocks_of(check_docs, monkeypatch, tmp_path, markdown)


def test_the_tabs_of_a_block_stay_as_the_reader_copies_them(check_docs, monkeypatch, tmp_path):
    """The hash must follow the text of the README, and a tab that Python rejects must stay a tab to be rejected."""
    markdown = "## A\n\n```python\nif x:\n\ty = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "if x:\n\ty = 2")]


def test_the_tabs_of_a_block_in_a_list_stay_when_the_indent_is_the_same_text(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n- Step\n\n    ```python\n    if x:\n    \ty = 2\n    ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "if x:\n\ty = 2")]


def test_quote_marks_inside_a_block_that_is_not_in_a_quote_are_code(check_docs, monkeypatch, tmp_path):
    """A console session or a continuation line starts with the characters of a quote and must stay as written."""
    markdown = "## A\n\n```python\n>>> x = 1\n  > b):\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", ">>> x = 1\n  > b):")]


@pytest.mark.parametrize("marker", ["-", "*", "+", "1.", "12)"])
def test_a_quote_inside_a_list_item_holds_a_block(check_docs, monkeypatch, tmp_path, marker):
    markdown = f"## A\n\n{marker} > ```python\n  > x = 1\n  > ```\n\n```python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1"), ("A::1", "y = 2")]


def test_a_list_item_that_is_not_a_quote_is_left_alone(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n- > not a fence\n- ```x``` nor this\n\n```python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "y = 2")]


@pytest.mark.parametrize("info", ["python,ignore", "python{1,2}", "{.python}", "{ .python .numberLines }", "python:file.py"])
def test_the_language_may_be_followed_by_attributes_without_a_space(check_docs, monkeypatch, tmp_path, info):
    markdown = f"## A\n\n```{info}\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1")]


NOT_PYTHON = [
    "python-console",
    "python_traceback",
    "py-foo",
    "python=3",
    "python3.8",
    "pythonic",
    "py2x",
    "pycon",
    "{.python-console}",
    "{.pythonic}",
    "{#python}",
    "{python}",
    "{.py_foo .bash}",
]


@pytest.mark.parametrize("info", NOT_PYTHON)
def test_a_word_that_only_starts_like_python_is_not_python(check_docs, monkeypatch, tmp_path, info):
    """The word of the language ends at a space, a comma, a brace or a colon, and not at the first odd character."""
    markdown = f"## A\n\n```{info}\n>>> x = 1\n```\n\n```Python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "y = 2")]


@pytest.mark.parametrize("info", ["{#x .python}", "{.numberLines .python}", "{#x .a .python .b}", "{ .Python }", "{.py}"])
def test_python_may_be_any_class_of_a_pandoc_attribute_list(check_docs, monkeypatch, tmp_path, info):
    markdown = f"## A\n\n```{info}\nx = 1\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1")]


def test_a_console_session_in_a_quoted_block_keeps_its_prompt(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n> ```python\n> >>> x = 1\n> ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", ">>> x = 1")]


def test_only_the_marks_of_the_quote_that_holds_the_fence_are_taken_off(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n> ```python\n> x = 1\n> > y = 2\n> ```\n\n> > ```python\n> > >>> z = 3\n> > ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1\n> y = 2"), ("A::1", ">>> z = 3")]


@pytest.mark.parametrize("marker", ["-", "1.", "10.", "99)", "100.", "123456789."])
def test_a_quoted_block_in_a_list_item_is_found_whatever_the_width_of_the_marker(check_docs, monkeypatch, tmp_path, marker):
    pad = " " * (len(marker) + 1)
    markdown = f"## A\n\n{marker} > ```python\n{pad}> x = 1\n{pad}> >>> y\n{pad}> ```\n\n```python\nz = 3\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1\n>>> y"), ("A::1", "z = 3")]


def test_a_list_item_with_two_quotes_takes_off_both_marks_and_no_more(check_docs, monkeypatch, tmp_path):
    markdown = "## A\n\n- > > ```python\n  > > >>> x = 1\n  > > > y\n  > > ```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", ">>> x = 1\n> y")]


def test_a_quoted_block_in_a_list_item_whose_quote_ends_is_never_closed(check_docs, monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="never closed"):
        blocks_of(check_docs, monkeypatch, tmp_path, "## A\n\n- > ```python\n  > x = 1\n\n  > ```\n")


@pytest.mark.parametrize(
    "info",
    ['{title="a .python b"}', "{title='a .python b'}", '{.bash title="x .python"}', '{key=".python"}'],
)
def test_a_class_named_inside_a_quoted_attribute_value_is_not_a_class(check_docs, monkeypatch, tmp_path, info):
    markdown = f"## A\n\n```{info}\n>>> x = 1\n```\n\n```Python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "y = 2")]


def test_a_class_beside_a_quoted_attribute_value_is_still_a_class(check_docs, monkeypatch, tmp_path):
    markdown = '## A\n\n```{title="a b" .python}\nx = 1\n```\n'

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1")]


def test_the_slack_before_the_first_mark_does_not_widen_the_gap_between_marks(check_docs, monkeypatch, tmp_path):
    """Only the first mark may sit behind the width of a list marker; a second one four columns in is text, not a quote."""
    markdown = "## A\n\n10. > > ```python\n    > > x = 1\n    >     > y = 2\n    > > ```\n"

    with pytest.raises(ValueError, match="never closed"):
        blocks_of(check_docs, monkeypatch, tmp_path, markdown)


@pytest.mark.parametrize("info", ['{title="unterminated .python}', "{title='unterminated .python}", '{.bash title="x .python'])
def test_a_quote_that_is_never_closed_in_the_attributes_hides_what_follows_it(check_docs, monkeypatch, tmp_path, info):
    markdown = f"## A\n\n```{info}\n>>> x = 1\n```\n\n```Python\ny = 2\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "y = 2")]


@pytest.mark.parametrize("prefix, pad", [("- - ", "    "), ("1. - ", "     "), ("- 10. ", "      "), ("- - - ", "      ")])
def test_a_quote_in_a_nested_list_item_holds_a_block(check_docs, monkeypatch, tmp_path, prefix, pad):
    markdown = f"## A\n\n{prefix}> ```python\n{pad}> x = 1\n{pad}> >>> y\n{pad}> ```\n\n```python\nz = 3\n```\n"

    assert blocks_of(check_docs, monkeypatch, tmp_path, markdown) == [("A::0", "x = 1\n>>> y"), ("A::1", "z = 3")]
