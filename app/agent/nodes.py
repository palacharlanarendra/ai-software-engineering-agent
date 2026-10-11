import logging
from typing import Any, Dict

from app.agent.state import AgentState, PatchProposal, VerificationResult
from app.agent.patch import (
    create_unified_diff,
    validate_patch_syntax,
    apply_patch_safely,
    validate_target_path,
    create_patch_id,
    compute_content_checksum,
)
from app.agent.verifier import run_verification_tests
from app.ai.analyzer import analyze_code_task
from app.rag.retriever import search_code_semantic
from app.tools.repository import search_code

logger = logging.getLogger(__name__)


def validate_input_node(state: AgentState) -> Dict[str, Any]:
    """Validate task intake."""
    task = state.get("task", "")
    if not task or not task.strip():
        return {
            "status": "failed",
            "errors": state.get("errors", []) + ["Task input cannot be empty."],
        }

    return {
        "status": "validated",
        "retry_count": state.get("retry_count", 0),
        "max_retries": state.get("max_retries", 2),
        "errors": state.get("errors", []),
        "patch_applied": False,
        "approval_status": state.get("approval_status", "pending"),
    }


def retrieve_context_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve relevant repository snippets using semantic retrieval with keyword fallback."""
    task = state.get("task", "")
    snippets: list[dict] = []

    try:
        semantic_results = search_code_semantic(task, limit=5)
        for r in semantic_results:
            if hasattr(r, "file_path"):
                snippets.append({
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "content": r.content,
                    "score": r.score,
                })
            elif isinstance(r, dict):
                snippets.append({
                    "file_path": r.get("file_path", r.get("file", "")),
                    "start_line": r.get("start_line", r.get("line", 1)),
                    "end_line": r.get("end_line", r.get("line", 1)),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0.5),
                })
    except Exception as exc:
        logger.warning(f"Semantic search failed during node execution: {exc}")

    # If semantic search returned nothing, fallback to keyword search on key terms
    if not snippets:
        for word in task.split():
            clean_word = word.strip(".,;:?!'\"")
            if len(clean_word) >= 4:
                kw_results = search_code(clean_word)
                for kw in kw_results[:3]:
                    snippets.append({
                        "file_path": kw["file"],
                        "start_line": kw["line"],
                        "end_line": kw["line"],
                        "content": kw["content"],
                        "score": 0.5,
                    })
                if snippets:
                    break

    if not snippets:
        return {
            "retrieved_context": [],
            "status": "insufficient_context",
            "errors": state.get("errors", []) + ["No relevant repository context found for the task."],
        }

    return {
        "retrieved_context": snippets,
        "status": "retrieved",
    }


def analyze_evidence_node(state: AgentState) -> Dict[str, Any]:
    """Diagnose task and formulate findings based on retrieved evidence."""
    task = state.get("task", "")
    snippets = state.get("retrieved_context", [])

    # If retrying after a failed test verification, pass test failure feedback to LLM
    additional_context = None
    if state.get("test_results") and not state["test_results"]["passed"]:
        test_out = state["test_results"]["output"]
        additional_context = (
            f"PREVIOUS PATCH FAILED VERIFICATION (Attempt {state.get('retry_count', 1)}):\n"
            f"Test Output:\n{test_out[:1000]}\n"
            "Diagnose the failure and adjust your proposed change accordingly."
        )

    analysis_res = analyze_code_task(
        task=task,
        snippets=snippets,
        additional_context=additional_context,
        auto_retrieve=False,
    )

    analysis_dict = analysis_res.model_dump()
    new_status = "analyzed"
    if analysis_res.status == "insufficient_context":
        new_status = "insufficient_context"
    elif analysis_res.status == "error":
        new_status = "failed"

    return {
        "analysis": analysis_dict,
        "status": new_status,
        "errors": state.get("errors", []) + analysis_res.errors,
    }


def propose_patch_node(state: AgentState) -> Dict[str, Any]:
    """
    Generate structured patch proposal with unified diff, unique patch ID, and checksums.
    Strictly validates target path, prevents overwriting on read failures, validates syntax,
    and resets any stale approval state.
    """
    analysis = state.get("analysis") or {}
    proposed_changes = analysis.get("proposed_changes", [])

    if not proposed_changes:
        return {
            "patch": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "no_changes_needed",
        }

    first_change = proposed_changes[0]
    target_file = first_change.get("file_path", "")
    description = first_change.get("description", "")
    proposed_code = first_change.get("code_snippet", "")
    errors = list(state.get("errors", []))

    # 1. Validate target file path against security rules
    is_valid_path, target_path, path_err = validate_target_path(target_file)
    if not is_valid_path or target_path is None:
        errors.append(path_err or f"Invalid target path: {target_file}")
        return {
            "patch": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "failed",
            "errors": errors,
        }

    # 2. Retrieve original file content safely, distinguishing nonexistent files from read failures
    file_existed = target_path.exists()
    orig_content = ""

    if file_existed:
        if not target_path.is_file():
            errors.append(f"Cannot target non-file path: '{target_file}'")
            return {
                "patch": None,
                "approval_status": "not_needed",
                "approved_patch_id": None,
                "status": "failed",
                "errors": errors,
            }
        try:
            orig_content = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"Failed to read existing file '{target_file}': {exc}")
            return {
                "patch": None,
                "approval_status": "not_needed",
                "approved_patch_id": None,
                "status": "failed",
                "errors": errors,
            }

    proposed_content = proposed_code if proposed_code is not None else orig_content

    # 3. Detect no-op proposals on existing files
    if file_existed and proposed_content == orig_content:
        return {
            "patch": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "no_changes_needed",
            "errors": errors,
        }

    # 4. Strict syntax validation: if invalid, do NOT produce an approvable patch
    syntax_err = validate_patch_syntax(proposed_content, target_file)
    if syntax_err:
        errors.append(syntax_err)
        return {
            "patch": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "failed",
            "errors": errors,
        }

    # 5. Generate unified diff
    diff = create_unified_diff(orig_content, proposed_content, target_file)

    # 6. Generate deterministic full-SHA256 patch ID and checksums
    orig_checksum = compute_content_checksum(orig_content)
    prop_checksum = compute_content_checksum(proposed_content)
    patch_id = create_patch_id(target_file, proposed_content, orig_checksum)

    patch_proposal: PatchProposal = {
        "patch_id": patch_id,
        "file_path": target_file,
        "description": description,
        "diff": diff,
        "original_content": orig_content,
        "proposed_content": proposed_content,
        "expected_original_checksum": orig_checksum,
        "proposed_checksum": prop_checksum,
        "file_existed_before": file_existed,
    }

    return {
        "patch": patch_proposal,
        "approval_status": "pending",
        "approved_patch_id": None,  # Always reset approval state on fresh proposal
        "status": "awaiting_approval",
        "errors": errors,
    }


def apply_patch_node(state: AgentState) -> Dict[str, Any]:
    """
    Apply approved patch to disk only after strict human approval validation
    and complete proposal integrity verification.
    """
    approval = state.get("approval_status", "")
    patch = state.get("patch")

    if approval != "approved":
        return {
            "status": "rejected",
            "patch_applied": False,
        }

    if not patch:
        return {
            "status": "failed",
            "errors": state.get("errors", []) + ["No patch proposal available to apply."],
            "patch_applied": False,
        }

    # 1. Require non-empty approved_patch_id
    approved_id = state.get("approved_patch_id")
    if not approved_id or not str(approved_id).strip():
        return {
            "status": "rejected",
            "patch_applied": False,
            "errors": state.get("errors", []) + [
                "Approval rejected: approved_patch_id is missing or empty. "
                "Explicit approval must specify the exact patch ID."
            ],
        }

    # 2. Require approved_patch_id to match active patch ID exactly
    active_patch_id = patch.get("patch_id", "")
    if approved_id != active_patch_id:
        return {
            "status": "rejected",
            "patch_applied": False,
            "errors": state.get("errors", []) + [
                f"Patch mismatch: approved ID '{approved_id}' does not match active patch '{active_patch_id}'."
            ],
        }

    # 3. Bind approval to complete proposal integrity: recompute patch ID and checksums
    target_file = patch.get("file_path", "")
    proposed_content = patch.get("proposed_content", "")
    expected_orig_checksum = patch.get("expected_original_checksum")
    expected_prop_checksum = patch.get("proposed_checksum")

    computed_prop_checksum = compute_content_checksum(proposed_content)
    if expected_prop_checksum and computed_prop_checksum != expected_prop_checksum:
        return {
            "status": "failed",
            "patch_applied": False,
            "errors": state.get("errors", []) + [
                "Proposal tampering detected: proposed content does not match recorded checksum."
            ],
        }

    computed_patch_id = create_patch_id(target_file, proposed_content, expected_orig_checksum)
    if computed_patch_id != active_patch_id:
        return {
            "status": "failed",
            "patch_applied": False,
            "errors": state.get("errors", []) + [
                "Proposal tampering detected: patch ID does not match computed digest of target path and content."
            ],
        }

    # 4. Revalidate and apply safely with atomic replacement
    res = apply_patch_safely(
        file_path=target_file,
        proposed_content=proposed_content,
        expected_original_checksum=expected_orig_checksum,
    )

    if not res.success:
        return {
            "status": "apply_failed",
            "patch_applied": False,
            "errors": state.get("errors", []) + [res.error_message or "Failed to write patch."],
        }

    return {
        "status": "applied",
        "patch_applied": True,
        "original_file_content": res.original_content,
        "file_existed_before": res.file_existed_before,
        "expected_applied_checksum": computed_prop_checksum,
    }


def verify_patch_node(state: AgentState) -> Dict[str, Any]:
    """Run automated verification tests on applied patch with exception safety."""
    errors = list(state.get("errors", []))
    try:
        res = run_verification_tests()
    except Exception as exc:
        logger.error(f"Verification runner threw unexpected exception: {exc}")
        res = VerificationResult(
            passed=False,
            exit_code=-1,
            output=f"Verification execution error: {exc}",
            test_target="app/tests/",
        )
        errors.append(f"Verification failed with exception: {exc}")

    passed = res.get("passed", False)
    return {
        "test_results": res,
        "status": "verified" if passed else "verification_failed",
        "errors": errors,
    }
