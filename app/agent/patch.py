import ast
import difflib
import hashlib
from pathlib import Path
from typing import Optional, Tuple

from app.config import PROJECT_ROOT, IGNORED_DIRS, SENSITIVE_FILES

PERMITTED_EXTENSIONS = {
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".toml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".sh",
}


def compute_content_checksum(content: str) -> str:
    """Compute deterministic SHA256 checksum of content string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def create_patch_id(file_path: str, proposed_content: str) -> str:
    """Generate a unique, tamper-evident patch ID tied to the exact file and proposed content."""
    seed = f"{file_path}:{proposed_content}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"patch-{digest}"


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


def validate_target_path(file_path: str) -> Tuple[bool, Optional[Path], Optional[str]]:
    """
    Strictly validate a file path against repository security rules:
    - Rejects absolute paths
    - Rejects path traversal (escaping root)
    - Rejects ignored directories
    - Rejects sensitive files
    - Restricts to permitted file extensions

    Returns:
        (is_valid, resolved_path, error_message)
    """
    if not file_path or not file_path.strip():
        return False, None, "File path cannot be empty."

    # 1. Reject absolute paths
    raw_path = Path(file_path)
    if raw_path.is_absolute() or file_path.startswith("/") or file_path.startswith("\\"):
        return False, None, f"Access denied: absolute path '{file_path}' is not permitted."

    root = PROJECT_ROOT.resolve()
    target_path = (root / file_path).resolve()

    # 2. Path traversal security check (must stay inside root)
    if root not in target_path.parents and target_path != root:
        return False, None, f"Access denied: path '{file_path}' escapes repository root."

    relative_path = target_path.relative_to(root)

    # 3. Ignored directory check
    if any(part in IGNORED_DIRS for part in relative_path.parts):
        return False, None, f"Access denied: file '{file_path}' is inside an ignored directory."

    # 4. Sensitive files check
    if target_path.name in SENSITIVE_FILES:
        return False, None, f"Access denied: sensitive file '{file_path}' cannot be modified."

    # 5. Permitted file type check
    if target_path.suffix not in PERMITTED_EXTENSIONS:
        return False, None, f"Access denied: file extension '{target_path.suffix}' is not permitted for editing."

    return True, target_path, None


def apply_patch_safely(
    file_path: str,
    proposed_content: str,
    expected_original_checksum: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Safely write approved patch content to a repository file within permitted bounds.
    Revalidates the patch, path rules, syntax, and verifies that the file on disk
    has not changed since the proposal was generated.

    Returns:
        (success, original_content, error_message)
    """
    # 1. Validate path security and permissions
    valid_path, target_path, err = validate_target_path(file_path)
    if not valid_path or target_path is None:
        return False, None, err

    # 2. Syntax revalidation
    syntax_err = validate_patch_syntax(proposed_content, file_path)
    if syntax_err:
        return False, None, syntax_err

    # 3. Read current content and check for concurrent modifications
    original_content = ""
    if target_path.exists():
        if not target_path.is_file():
            return False, None, f"Cannot write to non-file path: {file_path}"
        try:
            original_content = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, None, f"Failed to read existing file: {exc}"

        # If an expected original checksum was provided, verify file has not changed
        if expected_original_checksum:
            current_checksum = compute_content_checksum(original_content)
            if current_checksum != expected_original_checksum:
                return (
                    False,
                    original_content,
                    "Conflict detected: The file on disk was modified after the patch proposal "
                    "was generated. Revalidation failed to prevent overwriting concurrent changes.",
                )
    else:
        # Parent directory must exist
        target_path.parent.mkdir(parents=True, exist_ok=True)

    # 4. Apply file write
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
    valid_path, target_path, err = validate_target_path(file_path)
    if not valid_path or target_path is None:
        return False, err

    try:
        target_path.write_text(original_content, encoding="utf-8")
        return True, None
    except OSError as exc:
        return False, f"Failed to rollback file {file_path}: {exc}"
