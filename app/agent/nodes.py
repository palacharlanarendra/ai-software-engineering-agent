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
            file_path = getattr(r, "file_path", None) or (r.get("file_path") if isinstance(r, dict) else "")
            start_line = getattr(r, "start_line", 1) or (r.get("start_line", 1) if isinstance(r, dict) else 1)
            end_line = getattr(r, "end_line", 1) or (r.get("end_line", 1) if isinstance(r, dict) else 1)
            score = getattr(r, "score", 0.5) or (r.get("score", 0.5) if isinstance(r, dict) else 0.5)
            content = getattr(r, "content", "") or (r.get("content", "") if isinstance(r, dict) else "")

            # Hydrate snippet from disk if available to guarantee 100% freshness
            try:
                from app.config import PROJECT_ROOT
                target_disk_path = (PROJECT_ROOT / file_path).resolve()
                if target_disk_path.is_file():
                    disk_lines = target_disk_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if disk_lines and start_line <= len(disk_lines):
                        content = "\n".join(disk_lines[max(0, start_line - 1): min(len(disk_lines), end_line)])
            except Exception:
                pass

            snippets.append({
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "content": content,
                "score": score,
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

    # Multi-file discovery: check if task explicitly references other repository files
    try:
        from app.tools.repository import list_files, read_file
        repo_files = list_files()
        already_covered_files = {s["file_path"] for s in snippets}
        for rf in repo_files:
            rf_name = rf.split("/")[-1]
            if (rf in task or rf_name in task) and rf not in already_covered_files:
                file_content = read_file(rf)
                if file_content and not file_content.startswith("Access denied") and not file_content.startswith("file not found:"):
                    lines = file_content.splitlines()
                    snip_content = "\n".join(lines[:min(len(lines), 40)])
                    snippets.append({
                        "file_path": rf,
                        "start_line": 1,
                        "end_line": min(len(lines), 40),
                        "content": snip_content,
                        "score": 0.8,
                    })
    except Exception as exc:
        logger.debug(f"Multi-file mention scan skipped: {exc}")

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
    Generate structured patch proposal across one or multiple files with unified diffs,
    unique patch IDs, bundle checksum, and tamper-evident hashes.
    Strictly validates target paths, prevents overwriting on read failures, validates syntax,
    and resets any stale approval state.
    """
    analysis = state.get("analysis") or {}
    proposed_changes = analysis.get("proposed_changes", [])

    if not proposed_changes:
        return {
            "patch": None,
            "patches": [],
            "bundle_patch_id": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "no_changes_needed",
        }

    errors = list(state.get("errors", []))

    # Group proposed changes by target file path for multi-edit aggregation
    changes_by_file: dict[str, list[dict]] = {}
    for change in proposed_changes:
        fp = (change.get("file_path") or "").strip()
        if fp:
            changes_by_file.setdefault(fp, []).append(change)

    if not changes_by_file:
        return {
            "patch": None,
            "patches": [],
            "bundle_patch_id": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "no_changes_needed",
        }

    patch_proposals: list[PatchProposal] = []
    has_validation_failure = False

    for target_file, file_changes in changes_by_file.items():
        # 1. Validate target file path against security rules
        is_valid_path, target_path, path_err = validate_target_path(target_file)
        if not is_valid_path or target_path is None:
            errors.append(path_err or f"Invalid target path: {target_file}")
            has_validation_failure = True
            break

        # 2. Retrieve original file content safely
        file_existed = target_path.exists()
        orig_content = ""

        if file_existed:
            if not target_path.is_file():
                errors.append(f"Cannot target non-file path: '{target_file}'")
                has_validation_failure = True
                break
            try:
                orig_content = target_path.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"Failed to read existing file '{target_file}': {exc}")
                has_validation_failure = True
                break

        # 3. Determine proposed content (supporting snippet-level replacements on existing files)
        if file_existed:
            proposed_content = orig_content
            file_replacement_failed = False
            for change in file_changes:
                orig_snip = change.get("original_snippet") or ""
                prop_snip = change.get("code_snippet") or ""

                if orig_snip.strip():
                    if orig_snip in proposed_content:
                        proposed_content = proposed_content.replace(orig_snip, prop_snip, 1)
                    elif orig_snip.strip() in proposed_content:
                        proposed_content = proposed_content.replace(orig_snip.strip(), prop_snip.strip(), 1)
                    else:
                        errors.append(f"Target original_snippet not found in {target_file}")
                        file_replacement_failed = True
                        break
                elif prop_snip and prop_snip != proposed_content:
                    matched_ev = None
                    for ev in analysis.get("evidence", []):
                        ev_file = ev.get("file_path") if isinstance(ev, dict) else getattr(ev, "file_path", "")
                        ev_snip = ev.get("snippet") if isinstance(ev, dict) else getattr(ev, "snippet", "")
                        if ev_file == target_file and ev_snip and ev_snip.strip() in proposed_content:
                            matched_ev = ev_snip.strip()
                            break

                    if matched_ev and len(prop_snip.splitlines()) < max(2, len(proposed_content.splitlines()) // 2):
                        proposed_content = proposed_content.replace(matched_ev, prop_snip.strip(), 1)
                    else:
                        proposed_content = prop_snip
                else:
                    proposed_content = prop_snip

            if file_replacement_failed:
                has_validation_failure = True
                break
        else:
            first_snip = file_changes[0].get("code_snippet", "")
            proposed_content = first_snip if first_snip is not None else ""

        # 4. Detect no-op proposals on existing files
        if file_existed and proposed_content == orig_content:
            continue

        # 5. Strict syntax validation
        syntax_err = validate_patch_syntax(proposed_content, target_file)
        if syntax_err:
            errors.append(syntax_err)
            has_validation_failure = True
            break

        # 6. Generate unified diff and checksums
        diff = create_unified_diff(orig_content, proposed_content, target_file)
        orig_checksum = compute_content_checksum(orig_content)
        prop_checksum = compute_content_checksum(proposed_content)
        patch_id = create_patch_id(target_file, proposed_content, orig_checksum)

        description = file_changes[0].get("description", "") or f"Update {target_file}"

        patch_proposals.append({
            "patch_id": patch_id,
            "file_path": target_file,
            "description": description,
            "diff": diff,
            "original_content": orig_content,
            "proposed_content": proposed_content,
            "expected_original_checksum": orig_checksum,
            "proposed_checksum": prop_checksum,
            "file_existed_before": file_existed,
        })

    if has_validation_failure:
        return {
            "patch": None,
            "patches": [],
            "bundle_patch_id": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "failed",
            "errors": errors,
        }

    if not patch_proposals:
        return {
            "patch": None,
            "patches": [],
            "bundle_patch_id": None,
            "approval_status": "not_needed",
            "approved_patch_id": None,
            "status": "no_changes_needed",
            "errors": errors,
        }

    from app.agent.patch import create_bundle_patch_id
    bundle_id = create_bundle_patch_id(patch_proposals)
    primary_patch = patch_proposals[0]

    return {
        "patch": primary_patch,
        "patches": patch_proposals,
        "bundle_patch_id": bundle_id,
        "approval_status": "pending",
        "approved_patch_id": None,  # Always reset approval state on fresh proposal
        "status": "awaiting_approval",
        "errors": errors,
    }


def apply_patch_node(state: AgentState) -> Dict[str, Any]:
    """
    Apply approved patch to disk only after strict human approval validation
    and complete proposal integrity verification across all target files in changeset.
    """
    approval = state.get("approval_status", "")
    patches = state.get("patches")
    if not patches and state.get("patch"):
        patches = [state["patch"]]

    if approval != "approved":
        return {
            "status": "rejected",
            "patch_applied": False,
        }

    if not patches:
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

    # 2. Check approval match: can approve bundle_patch_id or matching individual patch_id
    bundle_id = state.get("bundle_patch_id")
    all_patch_ids = [p.get("patch_id") for p in patches if p.get("patch_id")]
    primary_patch_id = patches[0].get("patch_id") if patches else ""

    approved_match = (
        approved_id == bundle_id or
        approved_id == primary_patch_id or
        approved_id in all_patch_ids
    )

    if not approved_match:
        return {
            "status": "rejected",
            "patch_applied": False,
            "errors": state.get("errors", []) + [
                f"Patch mismatch: approved ID '{approved_id}' does not match active patch '{primary_patch_id}'."
            ],
        }

    # 3. Bind approval to proposal integrity: verify checksums and patch IDs of all patches
    for patch in patches:
        target_file = patch.get("file_path", "")
        proposed_content = patch.get("proposed_content", "")
        expected_orig_checksum = patch.get("expected_original_checksum")
        expected_prop_checksum = patch.get("proposed_checksum")
        active_id = patch.get("patch_id", "")

        computed_prop_checksum = compute_content_checksum(proposed_content)
        if expected_prop_checksum and computed_prop_checksum != expected_prop_checksum:
            return {
                "status": "failed",
                "patch_applied": False,
                "errors": state.get("errors", []) + [
                    f"Proposal tampering detected: proposed content does not match recorded checksum for {target_file}."
                ],
            }

        computed_patch_id = create_patch_id(target_file, proposed_content, expected_orig_checksum)
        if computed_patch_id != active_id:
            return {
                "status": "failed",
                "patch_applied": False,
                "errors": state.get("errors", []) + [
                    f"Proposal tampering detected: patch ID does not match computed digest of target path and content for {target_file}."
                ],
            }

    # 4. Safely apply all patches transactionally
    from app.agent.patch import apply_multi_patch_safely
    success, applied_records, err_msg = apply_multi_patch_safely(patches)
    if not success:
        return {
            "status": "apply_failed",
            "patch_applied": False,
            "errors": state.get("errors", []) + [err_msg or "Failed to write patch."],
        }

    first_rec = applied_records[0] if applied_records else {}
    orig_contents_map = {r["file_path"]: r["original_content"] for r in applied_records}
    existed_map = {r["file_path"]: r["file_existed_before"] for r in applied_records}
    checksums_map = {r["file_path"]: r["applied_checksum"] for r in applied_records}

    return {
        "status": "applied",
        "patch_applied": True,
        "applied_patches": applied_records,
        "original_file_content": first_rec.get("original_content"),
        "file_existed_before": first_rec.get("file_existed_before", True),
        "expected_applied_checksum": first_rec.get("applied_checksum"),
        "original_file_contents": orig_contents_map,
        "files_existed_before": existed_map,
        "expected_applied_checksums": checksums_map,
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
