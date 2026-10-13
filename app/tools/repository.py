import ast
from pathlib import Path
from typing import Optional
from app.config import PROJECT_ROOT, IGNORED_DIRS, SENSITIVE_FILES


def list_files(directory: str = "") -> list[str]:
    """
    List repository files while skipping ignored directories.
    Optionally filter by sub-directory.
    """
    files = []
    root = PROJECT_ROOT.resolve()
    base_dir = (root / directory).resolve() if directory else root

    if root not in base_dir.parents and base_dir != root:
        return []

    for path in base_dir.rglob("*"):
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            continue

        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        if not path.is_file():
            continue

        if path.name in SENSITIVE_FILES:
            continue

        files.append(relative_path.as_posix())

    return sorted(files)


def read_file(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """
    Read the contents of a file inside the repository.
    Optionally extracts a specific 1-indexed line range [start_line, end_line].

    Args:
        file_path: Relative path of the file.
        start_line: Optional 1-indexed start line.
        end_line: Optional 1-indexed end line.
    """
    root = PROJECT_ROOT.resolve()
    path = (root / file_path).resolve()

    if root not in path.parents and path != root:
        return "Access denied."

    if not path.exists():
        return f"file not found: {file_path}"

    if not path.is_file():
        return f"Not a file: {file_path}"

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Failed to read file: {exc}"

    if start_line is not None or end_line is not None:
        lines = content.splitlines(keepends=True)
        s = max(0, (start_line - 1)) if start_line is not None else 0
        e = min(len(lines), end_line) if end_line is not None else len(lines)
        return "".join(lines[s:e])

    return content


def search_code(query: str, path_filter: Optional[str] = None) -> list[dict]:
    """Search repository files for a case-insensitive text match."""

    if not query or not query.strip():
        return []

    results = []
    root = PROJECT_ROOT.resolve()
    max_file_size = 1_000_000
    max_results = 50

    for path in root.rglob("*"):
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            continue

        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        if path.name in SENSITIVE_FILES:
            continue

        if not path.is_file():
            continue

        rel_posix = relative_path.as_posix()
        if path_filter and not rel_posix.startswith(path_filter):
            continue

        try:
            if path.stat().st_size > max_file_size:
                continue

            content = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            if query.casefold() in line.casefold():
                results.append({
                    "file": rel_posix,
                    "line": line_number,
                    "content": line.strip(),
                })

                if len(results) >= max_results:
                    return results

    return results


def inspect_symbols(file_path: str) -> dict:
    """
    Extract top-level functions, classes, async functions, and imports
    from a Python file using AST inspection.
    """
    content = read_file(file_path)
    if content.startswith("Access denied.") or content.startswith("file not found:") or content.startswith("Not a file:"):
        return {"error": content, "symbols": []}

    if not file_path.endswith(".py"):
        return {"file_path": file_path, "symbols": [], "note": "Not a Python file"}

    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError as err:
        return {"error": f"SyntaxError parsing {file_path}: {err}", "symbols": []}

    symbols = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            symbols.append({
                "type": "function",
                "name": node.name,
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "args": [a.arg for a in node.args.args],
            })
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.append({
                "type": "async_function",
                "name": node.name,
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "args": [a.arg for a in node.args.args],
            })
        elif isinstance(node, ast.ClassDef):
            methods = [
                m.name for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            symbols.append({
                "type": "class",
                "name": node.name,
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "methods": methods,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                symbols.append({"type": "import", "name": alias.name, "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                symbols.append({"type": "import_from", "module": mod, "name": alias.name, "line": node.lineno})

    return {"file_path": file_path, "symbols": symbols}


def find_references(symbol: str) -> list[dict]:
    """Find all references or usages of a symbol across repository code."""
    if not symbol or not symbol.strip():
        return []
    return search_code(symbol.strip())
