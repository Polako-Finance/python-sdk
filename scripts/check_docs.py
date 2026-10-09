"""
Check that the python code blocks in the documentation still match the SDK.

The documentation is the source of truth and knows nothing about this script. The script follows the docs:

* every python block of the markdown docs, and every file in ``examples/``, is pinned by a hash in
  ``docs_manifest.json``;
* when a block or a file is edited, added or removed the check fails, a developer reviews the change and runs
  ``python scripts/check_docs.py --update`` (or ``make docs-update``) to accept it;
* every pinned block is checked statically (nothing is executed): syntax, ``from polako.sdk import ...`` names,
  and that calls to SDK classes, SDK functions and client methods fit the real signatures.

Usage:
    python scripts/check_docs.py            # verify
    python scripts/check_docs.py --update   # accept the current docs (keeps the check kind of known blocks)
"""

import argparse
import ast
import hashlib
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import polako.sdk as sdk

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).with_name("docs_manifest.json")
DOCS = ["README.md", "README.pypi.md", "examples/README.md"]
KIND_STATIC = "static"  # syntax + imports + call signatures
KIND_SKIP = "skip"  # pinned by hash only (e.g. pseudo code that is not meant to be checked)

CLIENT = sdk.PolakoClient
CLIENT_METHODS = {name for name, _ in inspect.getmembers(CLIENT, inspect.isfunction) if not name.startswith("_")}


FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]+")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
QUOTE = re.compile(r"^(?: {0,3}>[ ]?)+")
INDENT = re.compile(r"[ \t]*")
PYTHON_LANGUAGES = frozenset({"python", "py", "python3", "py3"})  # ``pycon`` is a console session, not code to run


def _columns(whitespace: str) -> int:
    return len(whitespace.expandtabs(4))


def _dedent(line: str, indent: str) -> str:
    """
    Take the indent of the opening fence off a line, leaving the rest of the text as it is written.

    When the line starts with the very same characters they are cut off; a line indented in another way (tabs where the fence
    has spaces) loses the same number of columns (a tab counts to the next multiple of four), or all it has.
    """
    if line.startswith(indent):
        return line[len(indent) :]
    leading = INDENT.match(line)[0]
    return leading.expandtabs(4)[_columns(indent) :] + line[len(leading) :]


def extract_blocks(path: Path) -> List[Tuple[str, str]]:
    """
    Return (key, code) for every python fenced block; key = file::nearest heading::ordinal under it.

    The language of a fence is the first word of its info string, in any case: ``python``, ``py``, ``python3``, ``py3``.
    Every kind of fenced block is followed to its end, so a ``# comment`` line inside a bash or text block is not taken for
    a heading. A fence is closed by a fence of the same character that is at least as long as the one that opened it. A
    fence that is never closed would swallow the rest of the file, so it is an error. A line of backticks followed by text
    that holds backticks (``` `x` ``` in a sentence) is inline code, not a fence. A closing fence is indented by at most three
    columns more than the opening one, so a line of backticks indented deeper inside a block is text of the block.

    As in CommonMark, a fence indented by four columns or more is a fence only inside a list item (then its code is dedented
    by the indent of the opening fence); anywhere else it is an indented code block and is not looked at. A list lasts
    until a heading or a paragraph that is not indented and comes after a blank line. A heading may be indented by up to
    three spaces. A fence inside a quote (``> ```python``) is read without the quote marks; a quote that ends before the
    fence does leaves the block never closed.

    Raises:
        ValueError: If a fenced block is never closed
    """
    blocks: List[Tuple[str, str]] = []
    heading, counter = "", {}
    fence, current, opened_at = None, [], 0  # fence: (character, length, is_python, indent, quoted) inside a fenced block
    in_list, after_blank = False, False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        quote = QUOTE.match(raw)
        line = raw[quote.end() :] if quote else raw
        if fence is None:
            opening = FENCE.match(line)
            inline = opening and opening["marker"][0] == "`" and "`" in opening["info"]
            if opening and not inline and (_columns(opening["indent"]) < 4 or in_list):
                marker, words = opening["marker"], opening["info"].split()
                is_python = bool(words) and words[0].lower() in PYTHON_LANGUAGES
                fence, current, opened_at = (marker[0], len(marker), is_python, opening["indent"], bool(quote)), [], number
            elif HEADING.match(line):
                heading, in_list = line.lstrip("# ").strip(), False
            elif LIST_ITEM.match(line):
                in_list = True
            elif line.strip() and not line[0].isspace() and after_blank:
                in_list = False
            after_blank = not line.strip() and fence is None
            continue
        character, length, is_python, indent, quoted = fence
        if quoted and not quote:
            break  # the quote ended, and the fence with it: it was never closed
        closing = re.match(rf"^([ \t]*){re.escape(character)}{{{length},}}\s*$", line)
        if closing and _columns(closing[1]) <= _columns(indent) + 3:
            if is_python:
                n = counter.get(heading, 0)
                counter[heading] = n + 1
                blocks.append((f"{path.relative_to(ROOT).as_posix()}::{heading}::{n}", "\n".join(current)))
            fence = None
        elif is_python:
            current.append(_dedent(line, indent))
    if fence is not None:
        raise ValueError(f"{path.name}: the block opened at line {opened_at} is never closed")
    return blocks


def digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]


def _bind(signature: inspect.Signature, call: ast.Call, skip_first: bool) -> str:
    elided = any(isinstance(a, ast.Constant) and a.value is Ellipsis for a in call.args)
    if elided or any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return ""  # `...`, *args, **kwargs: the arguments are elided or unknown, nothing to check statically
    args = [None] * len(call.args)
    kwargs = {k.arg: None for k in call.keywords}
    try:
        signature.bind(*([None] if skip_first else []), *args, **kwargs)
    except TypeError as e:
        return str(e)
    return ""


def check_static(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error: {e}"]

    errors: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "polako.sdk":
            errors += [f"'{a.name}' is not exported by polako.sdk" for a in node.names if not hasattr(sdk, a.name)]
        elif isinstance(node, ast.Call):
            func, message, label = node.func, "", ""
            if isinstance(func, ast.Name) and inspect.isclass(getattr(sdk, func.id, None)):
                label, message = func.id, _bind(inspect.signature(getattr(sdk, func.id)), node, False)
            elif isinstance(func, ast.Name) and inspect.isfunction(getattr(sdk, func.id, None)):
                label, message = func.id, _bind(inspect.signature(getattr(sdk, func.id)), node, False)
            elif isinstance(func, ast.Attribute) and func.attr in CLIENT_METHODS:
                static = isinstance(inspect.getattr_static(CLIENT, func.attr), staticmethod)
                label = func.attr
                message = _bind(inspect.signature(getattr(CLIENT, func.attr)), node, skip_first=not static)
            if message:
                errors.append(f"call {label}(...) does not fit the SDK: {message}")
    return errors


def load_manifest() -> Dict[str, Dict[str, str]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def current_blocks() -> Dict[str, str]:
    found: Dict[str, str] = {}
    for doc in DOCS:
        for key, code in extract_blocks(ROOT / doc):
            found[key] = code
    for example in sorted((ROOT / "examples").glob("*.py")):
        found[f"{example.relative_to(ROOT).as_posix()}::file::0"] = example.read_text(encoding="utf-8")
    return found


def verify() -> int:
    manifest, problems = load_manifest(), []
    try:
        blocks = current_blocks()
    except ValueError as e:
        print(f"BROKEN DOC     {e}")
        return 1
    for key, code in blocks.items():
        entry = manifest.get(key)
        if entry is None:
            problems.append(f"NEW BLOCK      {key}")
        elif entry["hash"] != digest(code):
            problems.append(f"CHANGED BLOCK  {key}")
        elif entry["check"] == KIND_STATIC:
            problems += [f"{key}: {e}" for e in check_static(code)]
    problems += [f"REMOVED BLOCK  {key}" for key in manifest if key not in blocks]
    for p in problems:
        print(p)
    if problems:
        print("\nIf the documentation change is intended, review it and run: python scripts/check_docs.py --update")
        return 1
    print(f"docs ok: {len(blocks)} python blocks")
    return 0


def update() -> int:
    manifest = load_manifest()
    try:
        blocks = current_blocks()
    except ValueError as e:
        print(f"BROKEN DOC     {e}")
        return 1
    updated = {k: {"hash": digest(c), "check": manifest.get(k, {}).get("check", KIND_STATIC)} for k, c in blocks.items()}
    MANIFEST.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest updated: {len(updated)} blocks")
    return verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="accept the current documentation")
    sys.exit(update() if parser.parse_args().update else verify())
