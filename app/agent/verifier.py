import subprocess
import sys
from typing import Optional

from app.agent.state import VerificationResult
from app.config import PROJECT_ROOT


def validate_test_target(target: str) -> tuple[bool, Optional[str]]:
    """
    Strictly validate that the test target is a safe relative test path inside app/tests,
    preventing arbitrary pytest flags, absolute paths, or directory traversal.
    """
    if not target or not target.strip():
        return False, "Test target cannot be empty."

    clean_target = target.strip()
    if clean_target.startswith("-"):
        return False, f"Access denied: CLI flags are not permitted in test target ('{clean_target}')."

    if clean_target.startswith("/") or clean_target.startswith("\\"):
        return False, f"Access denied: Absolute paths are not permitted in test target ('{clean_target}')."

    root = PROJECT_ROOT.resolve()
    # Support target expressions like app/tests/test_repository.py::TestClass::test_func
    base_file_path = clean_target.split("::")[0]
    resolved_path = (root / base_file_path).resolve()

    if root not in resolved_path.parents and resolved_path != root:
        return False, f"Access denied: Test target escapes repository root ('{clean_target}')."

    tests_root = (root / "app" / "tests").resolve()
    if tests_root not in resolved_path.parents and resolved_path != tests_root:
        return False, f"Access denied: Test target must reside inside 'app/tests' ('{clean_target}')."

    return True, None


def run_verification_tests(
    test_target: Optional[str] = None,
    timeout: int = 45,
) -> VerificationResult:
    """
    Run constrained automated tests using pytest against the repository.

    Args:
        test_target: Optional relative test path or function (e.g., 'app/tests/test_repository.py').
                     If None, runs all tests under app/tests/.
        timeout: Subprocess timeout in seconds.

    Returns:
        VerificationResult with passed status, exit code, and captured output.
    """
    target = test_target or "app/tests/"

    # Validate target safety
    is_valid, err = validate_test_target(target)
    if not is_valid:
        return VerificationResult(
            passed=False,
            exit_code=-1,
            output=f"Security error: {err}",
            test_target=target,
        )

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        target,
    ]

    try:
        proc = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )

        passed = proc.returncode == 0
        return VerificationResult(
            passed=passed,
            exit_code=proc.returncode,
            output=proc.stdout,
            test_target=target,
        )

    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or "" if isinstance(exc.stdout, str) else ""
        return VerificationResult(
            passed=False,
            exit_code=-1,
            output=f"Verification timed out after {timeout} seconds.\n{output}",
            test_target=target,
        )

    except Exception as exc:
        return VerificationResult(
            passed=False,
            exit_code=-1,
            output=f"Failed to execute verification test process: {exc}",
            test_target=target,
        )
