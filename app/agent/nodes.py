import logging
from typing import Any, Dict

from app.agent.state import AgentState, PatchProposal
from app.agent.patch import create_unified_diff, validate_patch_syntax, apply_patch_safely
from app.agent.verifier import run_verification_tests
from app.ai.analyzer import analyze_code_task
from app.rag.retriever import search_code_semantic
from app.tools.repository import read_file, search_code

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
            snippets.append({
                "file_path": r.file_path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "content": r.content,
                "score": r.score,
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
    """Generate structured patch proposal with unified diff and syntax checks."""
    analysis = state.get("analysis") or {}
    proposed_changes = analysis.get("proposed_changes", [])

    if not proposed_changes:
        # Diagnosis concluded no code modifications required
        return {
            "patch": None,
            "approval_status": "not_needed",
            "status": "no_changes_needed",
        }

    first_change = proposed_changes[0]
    target_file = first_change.get("file_path", "")
    description = first_change.get("description", "")
    proposed_code = first_change.get("code_snippet", "")

    # Read original file content
    orig_content = read_file(target_file)
    if orig_content.startswith("file not found:") or orig_content.startswith("Access denied."):
        orig_content = ""

    # If proposed_code is empty, synthesize a minimal patch description
    proposed_content = proposed_code if proposed_code else orig_content

    # Generate unified diff
    diff = create_unified_diff(orig_content, proposed_content, target_file)

    # Validate syntax if python file
    syntax_err = validate_patch_syntax(proposed_content, target_file)
    errors = list(state.get("errors", []))
    if syntax_err:
        errors.append(syntax_err)

    patch_proposal: PatchProposal = {
        "file_path": target_file,
        "description": description,
        "diff": diff,
        "original_content": orig_content,
        "proposed_content": proposed_content,
    }

    return {
        "patch": patch_proposal,
        "approval_status": "pending",
        "status": "awaiting_approval",
        "errors": errors,
    }


def apply_patch_node(state: AgentState) -> Dict[str, Any]:
    """Apply approved patch to disk only after explicit human approval."""
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

    success, orig, err = apply_patch_safely(patch["file_path"], patch["proposed_content"])
    if not success:
        return {
            "status": "apply_failed",
            "patch_applied": False,
            "errors": state.get("errors", []) + [err or "Failed to write patch."],
        }

    return {
        "status": "applied",
        "patch_applied": True,
        "original_file_content": orig,
    }


def verify_patch_node(state: AgentState) -> Dict[str, Any]:
    """Run automated verification tests on applied patch."""
    res = run_verification_tests()
    passed = res["passed"]

    return {
        "test_results": res,
        "status": "verified" if passed else "verification_failed",
    }
