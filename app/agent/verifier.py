import subprocess
import sys
from typing import Optional

from app.agent.state import VerificationResult
from app.config import PROJECT_ROOT


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
