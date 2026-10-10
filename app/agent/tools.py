import ast
import difflib

from langchain_core.tools import tool

from app.config import PROJECT_ROOT, IGNORED_DIRS, SENSITIVE_FILES

from app.tools.repository import (
    list_files,
    read_file,
    search_code,
)

from app.rag.retriever import search_code_semantic
from app.ai.llm import llm


@tool
def semantic_repository_search(query: str) -> list[dict]:
    """
    Search the repository semantically.
    Useful for natural-language questions about how
    the code works.
    """

    results = search_code_semantic(
        query,
        limit=5,
    )

    return [
        {
            "file": result.payload["file_path"],
            "chunk": result.payload["chunk_index"],
            "content": result.payload["content"],
            "score": result.score,
        }
        for result in results
    ]
    
@tool
def list_repository_files() -> list[str]:
    """List all relevant files in the repository."""
    return list_files()


@tool
def read_repository_file(file_path: str) -> str:
    """Read the contents of a specific repository file."""
    return read_file(file_path)


@tool
def search_repository(query: str) -> list[dict]:
    """
    Search the repository for exact keyword matches.
    Useful when looking for function names, class names,
    variables, errors, or API paths.
    """
    return search_code(query)


@tool
def check_python_syntax(file_path: str) -> str:
    """
    Check a Python file for syntax errors without modifying it.
    Only checks files inside the repository.
    """
    root = PROJECT_ROOT.resolve()
    path = (root / file_path).resolve()

    # Prevent path traversal outside the repository.
    if root not in path.parents:
        return "Access denied: path must be inside the repository."

    relative_path = path.relative_to(root)

    # Prevent access to ignored directories.
    if any(part in IGNORED_DIRS for part in relative_path.parts):
        return "Access denied: file is inside an ignored directory."

    # Prevent access to sensitive files.
    if path.name in SENSITIVE_FILES:
        return "Access denied: sensitive files cannot be checked."

    # Only Python files are supported.
    if path.suffix != ".py":
        return "Unsupported file type: only Python files are supported."

    if not path.exists() or not path.is_file():
        return f"File not found: {file_path}"

    try:
        # Avoid reading excessively large files.
        if path.stat().st_size > 1_000_000:
            return "File too large: maximum supported size is 1 MB."

        source = path.read_text(encoding="utf-8")

        # Parse the source without executing it.
        ast.parse(source, filename=str(path))

    except SyntaxError as exc:
        return (
            f"Syntax error in {file_path}, "
            f"line {exc.lineno}, column {exc.offset}: {exc.msg}"
        )
    except (OSError, UnicodeError) as exc:
        return f"Could not inspect file: {exc}"

    return f"No Python syntax errors found in {file_path}."


@tool
def propose_python_syntax_fix(file_path: str) -> str:
    """
    Propose a minimal fix for a Python syntax error.
    Does not modify the original file.
    """
    root = PROJECT_ROOT.resolve()
    path = (root / file_path).resolve()

    if root not in path.parents:
        return "Access denied: path must be inside the repository."

    relative_path = path.relative_to(root)

    if any(part in IGNORED_DIRS for part in relative_path.parts):
        return "Access denied: file is inside an ignored directory."

    if path.name in SENSITIVE_FILES:
        return "Access denied: sensitive files cannot be repaired."

    if path.suffix != ".py":
        return "Unsupported file type: only Python files are supported."

    if not path.exists() or not path.is_file():
        return f"File not found: {file_path}"

    try:
        if path.stat().st_size > 1_000_000:
            return "File too large: maximum supported size is 1 MB."

        original = path.read_text(encoding="utf-8")
        ast.parse(original, filename=str(path))

        return (
            f"No syntax error found in {file_path}. "
            "No repair is needed."
        )
    except SyntaxError as exc:
        error = (
            f"Syntax error on line {exc.lineno}, "
            f"column {exc.offset}: {exc.msg}"
        )
    except (OSError, UnicodeError) as exc:
        return f"Could not read file: {exc}"

    prompt = f"""
You are a careful Python syntax repair assistant.

Fix only the syntax error described below.
Preserve the program's intended behavior.
Do not refactor or make unrelated changes.
Return only the complete corrected Python source code,
without Markdown fences or explanations.

File: {relative_path}
Error: {error}

Original source:
{original}
"""

    try:
        response = llm.invoke(prompt)
        proposed = response.content

        if not isinstance(proposed, str):
            return "Could not create a text-only repair proposal."

        proposed = proposed.strip()

        if proposed.startswith("```"):
            lines = proposed.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                proposed = "\n".join(lines[1:-1])

        ast.parse(proposed, filename=str(path))

    except SyntaxError as exc:
        return (
            "Gemini's proposed fix still has a syntax error: "
            f"line {exc.lineno}, column {exc.offset}: {exc.msg}. "
            "The original file was not changed."
        )
    except Exception as exc:
        return f"Could not generate or validate a repair: {exc}"

    diff = difflib.unified_diff(
        original.splitlines(),
        proposed.splitlines(),
        fromfile=f"{relative_path} (original)",
        tofile=f"{relative_path} (proposed)",
        lineterm="",
    )

    return (
        f"Validated repair proposal for {relative_path}\n"
        f"Original syntax error: {error}\n\n"
        "Review this diff. The original file has NOT been changed.\n\n"
        + "\n".join(diff)
        + "\n\nThe proposal passed ast.parse validation."
    )



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
