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


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*(\S*)")


def extract_blocks(path: Path) -> List[Tuple[str, str]]:
    """
    Return (key, code) for every python fenced block; key = file::nearest heading::ordinal under it.

    Every kind of fenced block is followed to its end, so a ``# comment`` line inside a bash or text block is not taken for
    a heading. A fence is closed by a fence of the same character that is at least as long as the one that opened it.
    """
    blocks: List[Tuple[str, str]] = []
    heading, counter = "", {}
    fence, current = None, []  # fence: (character, length, is_python) while inside a fenced block
    for line in path.read_text(encoding="utf-8").splitlines():
        if fence is None:
            opening = FENCE.match(line)
            if opening:
                marker = opening.group(1)
                fence, current = (marker[0], len(marker), opening.group(2).startswith("python")), []
            elif re.match(r"#{1,6} ", line):
                heading = line.lstrip("# ").strip()
            continue
        character, length, is_python = fence
        if re.match(rf"^ {{0,3}}{re.escape(character)}{{{length},}}\s*$", line):
            if is_python:
                n = counter.get(heading, 0)
                counter[heading] = n + 1
                blocks.append((f"{path.relative_to(ROOT).as_posix()}::{heading}::{n}", "\n".join(current)))
            fence = None
        elif is_python:
            current.append(line)
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
    manifest, blocks, problems = load_manifest(), current_blocks(), []
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
    updated = {
        k: {"hash": digest(c), "check": manifest.get(k, {}).get("check", KIND_STATIC)} for k, c in current_blocks().items()
    }
    MANIFEST.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest updated: {len(updated)} blocks")
    return verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="accept the current documentation")
    sys.exit(update() if parser.parse_args().update else verify())
