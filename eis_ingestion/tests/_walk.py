"""AST import-closure walker for EIS daemon trees. No DB. No network."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SKIP_TOP = {
    "typing", "pathlib", "datetime", "json", "os", "sys", "time", "configparser",
    "logging", "re", "math", "collections", "itertools", "functools", "hashlib",
    "uuid", "copy", "traceback", "argparse", "subprocess", "shutil", "tempfile",
    "gzip", "zipfile", "io", "csv", "xml", "html", "http", "urllib", "ssl",
    "socket", "select", "threading", "multiprocessing", "concurrent", "queue",
    "decimal", "enum", "dataclasses", "abc", "contextlib", "warnings", "inspect",
    "pkgutil", "importlib", "types", "signal", "atexit", "glob", "fnmatch",
    "posixpath", "ntpath", "stat", "errno", "pprint", "textwrap", "string",
    "base64", "binascii", "struct", "array", "weakref", "gc", "platform",
    "getpass", "pwd", "grp", "fcntl", "termios", "tty", "pty", "resource",
    "requests", "psycopg2", "lxml", "dotenv", "loguru", "dateutil", "rich",
}


def _resolve(root: Path, mod: str) -> Path | None:
    parts = mod.split(".")
    for cand in (root.joinpath(*parts).with_suffix(".py"), root.joinpath(*parts) / "__init__.py"):
        if cand.exists():
            return cand
    return None


def _relative(node: ast.ImportFrom, from_file: Path, root: Path) -> list[str]:
    pkg_dir = from_file.parent
    for _ in range(max(node.level - 1, 0)):
        pkg_dir = pkg_dir.parent
    bases: list[Path] = []
    if node.module:
        bases.append(pkg_dir.joinpath(*node.module.split(".")))
    else:
        bases.append(pkg_dir)
    out: list[str] = []
    for base in bases:
        for cand in (base.with_suffix(".py"), base / "__init__.py"):
            if cand.exists():
                try:
                    out.append(cand.relative_to(root).as_posix())
                except ValueError:
                    continue
        if node.module:
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            for cand in ((pkg_dir / alias.name).with_suffix(".py"), pkg_dir / alias.name / "__init__.py"):
                if cand.exists():
                    try:
                        out.append(cand.relative_to(root).as_posix())
                    except ValueError:
                        continue
    return out


def walk(root: Path, entry: str = "main.py") -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    files: list[str] = []
    missing: list[str] = []
    queue = [entry]
    while queue:
        rel = queue.pop()
        if rel in seen:
            continue
        seen.add(rel)
        path = root / rel
        if not path.exists():
            missing.append(rel)
            continue
        files.append(rel)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in SKIP_TOP or top in getattr(sys, "stdlib_module_names", ()):
                        continue
                    target = _resolve(root, alias.name)
                    if target is None:
                        continue
                    rel2 = target.relative_to(root).as_posix()
                    if rel2 not in seen:
                        queue.append(rel2)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    for rel2 in _relative(node, path, root):
                        if rel2 not in seen:
                            queue.append(rel2)
                    continue
                if not node.module:
                    continue
                names = [node.module]
                for alias in node.names:
                    if alias.name != "*":
                        names.append(f"{node.module}.{alias.name}")
                for name in names:
                    top = name.split(".")[0]
                    if top in SKIP_TOP or top in getattr(sys, "stdlib_module_names", ()):
                        continue
                    target = _resolve(root, name)
                    if target is None:
                        continue
                    rel2 = target.relative_to(root).as_posix()
                    if rel2 not in seen:
                        queue.append(rel2)
    return sorted(files), sorted(missing)
