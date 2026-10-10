import ast
import difflib
from pathlib import Path
from typing import Optional, Tuple

from app.config import PROJECT_ROOT, IGNORED_DIRS, SENSITIVE_FILES


def create_unified_diff(
    original: str,
    proposed: str,
    file_path: str,
) -> str:
    """Generate a clean unified diff between original and proposed file contents."""
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


def validate_patch_syntax(
    proposed_content: str,
    file_path: str,
) -> Optional[str]:
    """
    Validate Python syntax of proposed content without executing it.
    Returns error message if syntax is invalid, or None if valid.
    """
    if file_path.endswith(".py"):
        try:
            ast.parse(proposed_content, filename=file_path)
        except SyntaxError as exc:
            return (
                f"Python syntax error in proposal for {file_path} at line {exc.lineno}, "
                f"column {exc.offset}: {exc.msg}"
            )
    return None


def apply_patch_safely(
    file_path: str,
    proposed_content: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Safely write approved patch content to a repository file within permitted bounds.

    Returns:
        (success, original_content, error_message)
    """
    root = PROJECT_ROOT.resolve()
    target_path = (root / file_path).resolve()

    # 1. Path traversal security check
    if root not in target_path.parents and target_path != root:
        return False, None, f"Access denied: path {file_path} escapes repository root."

    relative_path = target_path.relative_to(root)

    # 2. Ignored directory check
    if any(part in IGNORED_DIRS for part in relative_path.parts):
        return False, None, f"Access denied: file {file_path} is inside an ignored directory."

    # 3. Sensitive files check
    if target_path.name in SENSITIVE_FILES:
        return False, None, f"Access denied: sensitive file {file_path} cannot be modified."

    # 4. Syntax validation
    syntax_err = validate_patch_syntax(proposed_content, file_path)
    if syntax_err:
        return False, None, syntax_err

    # 5. Read original content for backup/rollback
    original_content = ""
    if target_path.exists():
        if not target_path.is_file():
            return False, None, f"Cannot write to non-file path: {file_path}"
        try:
            original_content = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, None, f"Failed to read existing file: {exc}"
    else:
        # Parent directory must exist
        target_path.parent.mkdir(parents=True, exist_ok=True)

    # 6. Apply file write
    try:
        target_path.write_text(proposed_content, encoding="utf-8")
        return True, original_content, None
    except OSError as exc:
        return False, original_content, f"Failed to write file {file_path}: {exc}"


def rollback_patch(
    file_path: str,
    original_content: str,
) -> Tuple[bool, Optional[str]]:
    """Restore the previous file content following failed verification."""
    root = PROJECT_ROOT.resolve()
    target_path = (root / file_path).resolve()

    if root not in target_path.parents and target_path != root:
        return False, "Access denied during rollback."

    try:
        target_path.write_text(original_content, encoding="utf-8")
        return True, None
    except OSError as exc:
        return False, f"Failed to rollback file {file_path}: {exc}"
