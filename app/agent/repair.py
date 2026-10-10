
import ast
import difflib

from app.config import PROJECT_ROOT, IGNORED_DIRS, SENSITIVE_FILES


def apply_proposed_python_fix(
    file_path: str,
    proposed_source: str,
) -> str:
    """
    Validate a proposed Python fix, ask the human for approval,
    and write the file only after explicit approval.
    """
    root = PROJECT_ROOT.resolve()
    path = (root / file_path).resolve()

    # 1. Restrict access to files inside the repository.
    if root not in path.parents:
        return "Access denied: path must be inside the repository."

    relative_path = path.relative_to(root)

    if any(part in IGNORED_DIRS for part in relative_path.parts):
        return "Access denied: file is inside an ignored directory."

    if path.name in SENSITIVE_FILES:
        return "Access denied: sensitive files cannot be modified."

    if path.suffix != ".py":
        return "Unsupported file type: only Python files are supported."

    if not path.exists() or not path.is_file():
        return f"File not found: {file_path}"

    try:
        if path.stat().st_size > 1_000_000:
            return "File too large: maximum supported size is 1 MB."

        original = path.read_text(encoding="utf-8")

        # 2. Validate proposed code before asking for approval.
        ast.parse(proposed_source, filename=str(path))

    except SyntaxError as exc:
        return (
            "Rejected: proposed code has a syntax error at "
            f"line {exc.lineno}, column {exc.offset}: {exc.msg}"
        )
    except (OSError, UnicodeError) as exc:
        return f"Could not inspect file: {exc}"

    if original == proposed_source:
        return "No changes proposed."

    # 3. Show the exact changes before asking for approval.
    diff = difflib.unified_diff(
        original.splitlines(),
        proposed_source.splitlines(),
        fromfile=f"{relative_path} (original)",
        tofile=f"{relative_path} (proposed)",
        lineterm="",
    )

    print("\nProposed changes:\n")
    print("\n".join(diff))
    print("\nThe proposed code passed Python syntax validation.")

    approval = input(
        "\nApply these changes to the file? Type YES to confirm: "
    ).strip()

    if approval != "YES":
        return "Cancelled. The original file was not changed."

    # 4. Check that nobody changed the file while approval was pending.
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"Could not re-read file: {exc}"

    if current != original:
        return (
            "Cancelled: the file changed while approval was pending. "
            "Review the latest file and generate a new proposal."
        )

    # 5. Write only after explicit human approval.
    try:
        path.write_text(proposed_source, encoding="utf-8")
    except OSError as exc:
        return f"Could not write the approved fix: {exc}"

    return f"Approved fix applied to {relative_path}."
