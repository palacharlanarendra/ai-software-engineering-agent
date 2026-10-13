import ast
import difflib
import hashlib
import os
import uuid
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
    """Compute deterministic full SHA256 checksum of content string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def create_patch_id(
    file_path: str,
    proposed_content: str,
    expected_original_checksum: Optional[str] = None,
) -> str:
    """
    Generate a unique, tamper-evident full-SHA256 patch ID tied to:
    the target path, the expected original content hash, and the proposed content hash.
    """
    orig_part = expected_original_checksum or compute_content_checksum("")
    prop_part = compute_content_checksum(proposed_content)
    seed = f"{file_path}:{orig_part}:{prop_part}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"patch-{digest}"


def create_bundle_patch_id(patches_or_ids: list) -> str:
    """
    Generate a unique, deterministic aggregate bundle patch ID from a collection of
    patch proposals or patch IDs.
    """
    ids = []
    for item in patches_or_ids:
        if isinstance(item, dict):
            pid = item.get("patch_id", "")
            if pid:
                ids.append(pid)
        elif isinstance(item, str) and item:
            ids.append(item)
    seed = ":".join(sorted(ids)) if ids else str(uuid.uuid4())
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"bundle-{digest}"



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
    - Rejects empty paths
    - Rejects absolute paths
    - Rejects path traversal (escaping root)
    - Rejects symlinks escaping repository root
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
    # Also catches symlinks pointing outside root via Path.resolve()
    if root not in target_path.parents and target_path != root:
        return False, None, f"Access denied: path '{file_path}' escapes repository root."

    # Verify that raw path did not attempt to traverse out via symlinks
    raw_unresolved = (root / file_path)
    if raw_unresolved.is_symlink():
        symlink_target = raw_unresolved.resolve()
        if root not in symlink_target.parents and symlink_target != root:
            return False, None, f"Access denied: symlink '{file_path}' points outside repository root."

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


def _atomic_write_file(target_path: Path, content: str) -> None:
    """Write content to target path atomically via a temporary file and atomic rename."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = target_path.with_name(f".{target_path.name}.tmp.{uuid.uuid4().hex}")
    try:
        temp_file.write_text(content, encoding="utf-8")
        os.replace(temp_file, target_path)
    except Exception:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise


class ApplyPatchResult(tuple):
    """
    Backwards-compatible tuple subclass representing the result of applying a patch.
    Unpacks as (success, original_content, error_message), while also exposing
    named properties and .file_existed_before.
    """
    def __new__(
        cls,
        success: bool,
        original_content: Optional[str],
        error_message: Optional[str],
        file_existed_before: bool = False,
    ):
        instance = super().__new__(cls, (success, original_content, error_message))
        instance.file_existed_before = file_existed_before
        return instance

    @property
    def success(self) -> bool:
        return self[0]

    @property
    def original_content(self) -> Optional[str]:
        return self[1]

    @property
    def error_message(self) -> Optional[str]:
        return self[2]


def apply_patch_safely(
    file_path: str,
    proposed_content: str,
    expected_original_checksum: Optional[str] = None,
) -> ApplyPatchResult:
    """
    Safely write approved patch content to a repository file within permitted bounds.
    Revalidates the patch, path rules, syntax, and verifies that the file on disk
    has not changed since the proposal was generated.

    Returns:
        ApplyPatchResult(success, original_content, error_message, file_existed_before)
    """
    # 1. Validate path security and permissions
    valid_path, target_path, err = validate_target_path(file_path)
    if not valid_path or target_path is None:
        return ApplyPatchResult(False, None, err, False)

    # 2. Syntax revalidation
    syntax_err = validate_patch_syntax(proposed_content, file_path)
    if syntax_err:
        return ApplyPatchResult(False, None, syntax_err, False)

    # 3. Read current content and check for concurrent modifications
    file_existed_before = target_path.exists()
    original_content = ""

    if file_existed_before:
        if not target_path.is_file():
            return ApplyPatchResult(False, None, f"Cannot write to non-file path: {file_path}", True)
        try:
            original_content = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return ApplyPatchResult(False, None, f"Failed to read existing file: {exc}", True)

        # If an expected original checksum was provided, verify file has not changed
        if expected_original_checksum:
            current_checksum = compute_content_checksum(original_content)
            if current_checksum != expected_original_checksum:
                return ApplyPatchResult(
                    False,
                    original_content,
                    "Conflict detected: The file on disk was modified after the patch proposal "
                    "was generated. Revalidation failed to prevent overwriting concurrent changes.",
                    True,
                )
    else:
        # File does not exist yet; if an expected original checksum was provided, it must match empty content
        if expected_original_checksum:
            empty_checksum = compute_content_checksum("")
            if expected_original_checksum != empty_checksum:
                return ApplyPatchResult(
                    False,
                    "",
                    "Conflict detected: Expected original content checksum does not match nonexistent file baseline.",
                    False,
                )

    # 4. Atomic file write
    try:
        _atomic_write_file(target_path, proposed_content)
        return ApplyPatchResult(True, original_content, None, file_existed_before)
    except OSError as exc:
        return ApplyPatchResult(False, original_content, f"Failed to write file {file_path}: {exc}", file_existed_before)


def rollback_patch(
    file_path: str,
    original_content: Optional[str] = None,
    file_existed_before: bool = True,
    expected_applied_checksum: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Restore the previous repository file state following failed verification.
    Conflict-aware:
    - If the file was newly created by the agent, removes it only if it still matches
      the exact content written by the agent.
    - If the file existed before, restores original content only if the file on disk
      matches the expected applied content (detects concurrent developer edits).
    - Uses atomic file replacement and handles filesystem exceptions explicitly.

    Returns:
        (success, error_message)
    """
    valid_path, target_path, err = validate_target_path(file_path)
    if not valid_path or target_path is None:
        return False, err

    # Case A: File does not exist on disk
    if not target_path.exists():
        if not file_existed_before:
            # File was created by agent and is already removed
            return True, None
        else:
            return False, f"Rollback conflict: file '{file_path}' was deleted before rollback could restore it."

    if not target_path.is_file():
        return False, f"Rollback conflict: path '{file_path}' is not a regular file."

    # Read current content on disk
    try:
        current_disk_content = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Rollback error: failed to read '{file_path}' from disk: {exc}"

    # Conflict check: verify file has not been modified since patch application
    if expected_applied_checksum:
        current_checksum = compute_content_checksum(current_disk_content)
        if current_checksum != expected_applied_checksum:
            return (
                False,
                f"Rollback conflict: file '{file_path}' was modified after patch application. "
                "Refusing to rollback to prevent destroying external concurrent modifications.",
            )

    # Case B: File was created by agent -> delete it safely
    if not file_existed_before:
        try:
            target_path.unlink()
            return True, None
        except OSError as exc:
            return False, f"Rollback error: failed to remove created file '{file_path}': {exc}"

    # Case C: File existed before -> restore original content atomically
    try:
        _atomic_write_file(target_path, original_content if original_content is not None else "")
        return True, None
    except OSError as exc:
        return False, f"Rollback error: failed to restore original content to '{file_path}': {exc}"


def apply_multi_patch_safely(
    patches: list,
) -> Tuple[bool, list, Optional[str]]:
    """
    Safely apply multiple file patches.
    Validates all files first. If any file fails to validate or write,
    all successfully written files in this batch are rolled back immediately.

    Returns:
        (success: bool, applied_records: list[dict], error_message: Optional[str])
    """
    if not patches:
        return False, [], "No patches provided to apply."

    applied_records = []
    # Phase 1: Pre-validation of all patches before applying any writes
    for p in patches:
        file_path = p.get("file_path", "")
        proposed_content = p.get("proposed_content", "")
        expected_orig_checksum = p.get("expected_original_checksum")

        valid_path, target_path, err = validate_target_path(file_path)
        if not valid_path or target_path is None:
            return False, [], f"Validation error for '{file_path}': {err}"

        syntax_err = validate_patch_syntax(proposed_content, file_path)
        if syntax_err:
            return False, [], f"Syntax error for '{file_path}': {syntax_err}"

        if target_path.exists():
            if not target_path.is_file():
                return False, [], f"Target path '{file_path}' is not a regular file."
            if expected_orig_checksum:
                try:
                    curr_content = target_path.read_text(encoding="utf-8")
                except OSError as exc:
                    return False, [], f"Failed to read existing file '{file_path}': {exc}"
                curr_checksum = compute_content_checksum(curr_content)
                if curr_checksum != expected_orig_checksum:
                    return False, [], (
                        f"Conflict detected for '{file_path}': disk content was modified after proposal."
                    )
        else:
            if expected_orig_checksum:
                empty_checksum = compute_content_checksum("")
                if expected_orig_checksum != empty_checksum:
                    return False, [], (
                        f"Conflict detected for '{file_path}': expected checksum does not match nonexistent file."
                    )

    # Phase 2: Atomic writes with automatic rollback on partial failure
    for p in patches:
        file_path = p.get("file_path", "")
        proposed_content = p.get("proposed_content", "")
        expected_orig_checksum = p.get("expected_original_checksum")

        res = apply_patch_safely(
            file_path=file_path,
            proposed_content=proposed_content,
            expected_original_checksum=expected_orig_checksum,
        )
        if not res.success:
            # Rollback any already applied patches in this transaction
            rollback_multi_patch(applied_records)
            return False, [], f"Failed applying patch to '{file_path}': {res.error_message}"

        applied_records.append({
            "file_path": file_path,
            "original_content": res.original_content,
            "file_existed_before": res.file_existed_before,
            "applied_checksum": compute_content_checksum(proposed_content),
        })

    return True, applied_records, None


def rollback_multi_patch(
    applied_records: list,
) -> Tuple[bool, list]:
    """
    Roll back a batch of applied patch records in reverse order.
    Returns:
        (all_succeeded: bool, list_of_error_messages: list[str])
    """
    all_success = True
    errors = []
    for rec in reversed(applied_records):
        file_path = rec.get("file_path", "")
        orig_content = rec.get("original_content")
        existed_before = rec.get("file_existed_before", True)
        applied_checksum = rec.get("applied_checksum")

        ok, err = rollback_patch(
            file_path=file_path,
            original_content=orig_content,
            file_existed_before=existed_before,
            expected_applied_checksum=applied_checksum,
        )
        if not ok:
            all_success = False
            errors.append(f"{file_path}: {err}")

    return all_success, errors

