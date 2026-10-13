from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from langgraph.checkpoint.memory import MemorySaver

from app.agent.state import AgentState, PatchProposal, VerificationResult
from app.agent.patch import (
    create_unified_diff,
    validate_patch_syntax,
    validate_target_path,
    apply_patch_safely,
    rollback_patch,
    compute_content_checksum,
    create_patch_id,
    _atomic_write_file,
)
from app.agent.nodes import (
    validate_input_node,
    retrieve_context_node,
    analyze_evidence_node,
    propose_patch_node,
    apply_patch_node,
    verify_patch_node,
)
from app.agent.graph import (
    build_agent_graph,
    rollback_and_retry_node,
    rollback_and_fail_node,
    route_after_validation,
    route_after_retrieval,
    route_after_analysis,
    route_after_propose,
    route_after_apply,
    route_after_verify,
    route_after_rollback_and_retry,
)
from app.agent.verifier import run_verification_tests, validate_test_target


# ==============================================================================
# Patch & Diff Unit Tests
# ==============================================================================


class TestPatchUtilities:
    def test_create_unified_diff(self):
        orig = "def hello():\n    return False\n"
        proposed = "def hello():\n    return True\n"
        diff = create_unified_diff(orig, proposed, "sample.py")

        assert "--- a/sample.py" in diff
        assert "+++ b/sample.py" in diff
        assert "-    return False" in diff
        assert "+    return True" in diff

    def test_validate_patch_syntax_catches_invalid_syntax(self):
        err = validate_patch_syntax("def broken(: pass", "broken.py")
        assert err is not None
        assert "Python syntax error" in err

    def test_validate_patch_syntax_accepts_valid_code(self):
        assert validate_patch_syntax("def ok(): pass\n", "valid.py") is None

    def test_apply_patch_safely_prevents_directory_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        success, orig, err = apply_patch_safely("../outside.py", "x = 1\n")
        assert not success
        assert "escapes repository root" in err

    def test_apply_patch_safely_rejects_absolute_paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        success, orig, err = apply_patch_safely("/etc/passwd", "root:x:0:0\n")
        assert not success
        assert "absolute path" in err

    def test_apply_patch_safely_rejects_unpermitted_extensions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        success, orig, err = apply_patch_safely("payload.exe", "MZ\x90\x00")
        assert not success
        assert "not permitted for editing" in err

    def test_apply_patch_safely_prevents_touching_sensitive_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        success, orig, err = apply_patch_safely(".env", "SECRET=exposed\n")
        assert not success
        assert "sensitive file" in err

    def test_apply_patch_safely_conflict_detection_when_file_changed_concurrently(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "module.py"
        target.write_text("v = 1\n", encoding="utf-8")

        initial_checksum = compute_content_checksum("v = 1\n")

        # Simulate concurrent edit to the file on disk while approval was pending
        target.write_text("v = 99\n", encoding="utf-8")

        # Attempt to apply patch expecting original checksum
        success, orig, err = apply_patch_safely(
            "module.py",
            "v = 2\n",
            expected_original_checksum=initial_checksum,
        )
        assert not success
        assert "Conflict detected" in err
        # Ensure file was not overwritten
        assert target.read_text(encoding="utf-8") == "v = 99\n"

    def test_apply_and_rollback_existing_file_patch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "hello.py"
        target.write_text("initial = True\n", encoding="utf-8")

        res = apply_patch_safely("hello.py", "initial = False\n")
        assert res.success
        assert res.original_content == "initial = True\n"
        assert res.file_existed_before is True
        assert target.read_text(encoding="utf-8") == "initial = False\n"

        applied_hash = compute_content_checksum("initial = False\n")
        rb_success, rb_err = rollback_patch(
            "hello.py",
            res.original_content,
            file_existed_before=True,
            expected_applied_checksum=applied_hash,
        )
        assert rb_success
        assert target.read_text(encoding="utf-8") == "initial = True\n"

    def test_rollback_newly_created_file_deletes_when_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "new_module.py"
        assert not target.exists()

        res = apply_patch_safely("new_module.py", "created = True\n")
        assert res.success
        assert res.file_existed_before is False
        assert target.exists()

        applied_hash = compute_content_checksum("created = True\n")
        rb_success, rb_err = rollback_patch(
            "new_module.py",
            original_content="",
            file_existed_before=False,
            expected_applied_checksum=applied_hash,
        )
        assert rb_success
        assert not target.exists()

    def test_rollback_detects_conflict_when_file_modified_externally(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "concurrent.py"
        target.write_text("orig = 1\n", encoding="utf-8")

        res = apply_patch_safely("concurrent.py", "orig = 2\n")
        assert res.success

        applied_hash = compute_content_checksum("orig = 2\n")
        # Simulate external modification while patch was applied
        target.write_text("orig = 999\n", encoding="utf-8")

        rb_success, rb_err = rollback_patch(
            "concurrent.py",
            original_content="orig = 1\n",
            file_existed_before=True,
            expected_applied_checksum=applied_hash,
        )
        assert not rb_success
        assert "Rollback conflict" in rb_err
        # Ensures external changes are not destroyed
        assert target.read_text(encoding="utf-8") == "orig = 999\n"

    def test_rollback_detects_conflict_when_created_file_modified_externally(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "created.py"
        res = apply_patch_safely("created.py", "c = 1\n")
        assert res.success

        # External modification to the newly created file
        target.write_text("c = 2\n", encoding="utf-8")

        rb_success, rb_err = rollback_patch(
            "created.py",
            original_content="",
            file_existed_before=False,
            expected_applied_checksum=compute_content_checksum("c = 1\n"),
        )
        assert not rb_success
        assert "Rollback conflict" in rb_err
        assert target.exists()

    def test_rollback_missing_file_when_existed_before_reports_conflict(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "deleted.py"
        target.write_text("val = 1\n", encoding="utf-8")

        res = apply_patch_safely("deleted.py", "val = 2\n")
        assert res.success

        # File is deleted externally before rollback
        target.unlink()

        rb_success, rb_err = rollback_patch(
            "deleted.py",
            original_content="val = 1\n",
            file_existed_before=True,
            expected_applied_checksum=compute_content_checksum("val = 2\n"),
        )
        assert not rb_success
        assert "deleted before rollback" in rb_err

    def test_atomic_write_file_preserves_target_on_failure(self, tmp_path):
        target = tmp_path / "atomic.py"
        target.write_text("original\n", encoding="utf-8")

        with patch("os.replace", side_effect=OSError("Simulated disk replacement error")):
            with pytest.raises(OSError):
                _atomic_write_file(target, "new_content\n")

        # Target file must remain untouched
        assert target.read_text(encoding="utf-8") == "original\n"

    def test_validate_target_path_rejects_empty_or_whitespace(self):
        valid, path, err = validate_target_path("   ")
        assert not valid
        assert "cannot be empty" in err

    def test_validate_target_path_rejects_ignored_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        valid, path, err = validate_target_path(".git/hooks/pre-commit.py")
        assert not valid
        assert "ignored directory" in err

    def test_validate_target_path_symlink_pointing_outside_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        outside = tmp_path.parent / "outside_target.py"
        outside.write_text("x = 1\n", encoding="utf-8")
        link = tmp_path / "symlink.py"
        link.symlink_to(outside)
        valid, path, err = validate_target_path("symlink.py")
        assert not valid
        assert "escapes repository root" in err or "outside repository root" in err

    def test_apply_patch_safely_rejects_target_being_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        subdir = tmp_path / "subdir.py"
        subdir.mkdir()
        res = apply_patch_safely("subdir.py", "x = 1\n")
        assert not res.success
        assert "non-file path" in res.error_message

    def test_apply_patch_safely_read_failure_on_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "unreadable.py"
        target.write_text("data\n", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("Read error")):
            res = apply_patch_safely("unreadable.py", "x = 1\n")
            assert not res.success
            assert "Failed to read existing file" in res.error_message

    def test_apply_patch_safely_expected_checksum_mismatch_for_new_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        res = apply_patch_safely("new.py", "x = 1\n", expected_original_checksum="mismatched_hash")
        assert not res.success
        assert "does not match nonexistent file baseline" in res.error_message

    def test_apply_patch_safely_write_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        with patch("app.agent.patch._atomic_write_file", side_effect=OSError("Disk full")):
            res = apply_patch_safely("new.py", "x = 1\n")
            assert not res.success
            assert "Failed to write file" in res.error_message

    def test_rollback_patch_created_file_already_deleted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        success, err = rollback_patch("never_created.py", file_existed_before=False)
        assert success
        assert err is None

    def test_rollback_patch_target_is_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        dir_path = tmp_path / "dir.py"
        dir_path.mkdir()
        success, err = rollback_patch("dir.py", original_content="x = 1\n", file_existed_before=True)
        assert not success
        assert "not a regular file" in err

    def test_rollback_patch_read_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "exist.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            success, err = rollback_patch("exist.py", original_content="x = 0\n", file_existed_before=True)
            assert not success
            assert "failed to read" in err

    def test_rollback_patch_unlink_error_on_created_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "created.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            success, err = rollback_patch(
                "created.py",
                file_existed_before=False,
                expected_applied_checksum=compute_content_checksum("x = 1\n"),
            )
            assert not success
            assert "failed to remove created file" in err

    def test_rollback_patch_atomic_write_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "exist.py"
        target.write_text("modified\n", encoding="utf-8")
        with patch("app.agent.patch._atomic_write_file", side_effect=OSError("Disk full")):
            success, err = rollback_patch(
                "exist.py",
                original_content="orig\n",
                file_existed_before=True,
                expected_applied_checksum=compute_content_checksum("modified\n"),
            )
            assert not success
            assert "failed to restore original content" in err


# ==============================================================================
# Verifier Security Unit Tests
# ==============================================================================


class TestVerifierSecurity:
    def test_validate_test_target_rejects_empty(self):
        valid, err = validate_test_target("   ")
        assert not valid
        assert "cannot be empty" in err

    def test_validate_test_target_rejects_cli_flags(self):
        valid, err = validate_test_target("-k test_foo")
        assert not valid
        assert "CLI flags are not permitted" in err

        valid, err = validate_test_target("--collect-only")
        assert not valid
        assert "CLI flags are not permitted" in err

    def test_validate_test_target_rejects_absolute_paths(self):
        valid, err = validate_test_target("/etc/passwd")
        assert not valid
        assert "Absolute paths are not permitted" in err

    def test_validate_test_target_rejects_path_traversal(self):
        valid, err = validate_test_target("../../outside.py")
        assert not valid
        assert "escapes repository root" in err

    def test_validate_test_target_rejects_files_outside_app_tests(self):
        valid, err = validate_test_target("app/main.py")
        assert not valid
        assert "must reside inside 'app/tests'" in err

    def test_validate_test_target_accepts_valid_test_paths(self):
        valid, err = validate_test_target("app/tests/test_repository.py")
        assert valid
        assert err is None

        valid, err = validate_test_target("app/tests/test_repository.py::TestClass::test_func")
        assert valid
        assert err is None

    def test_run_verification_tests_aborts_on_unsafe_target(self):
        res = run_verification_tests(test_target="-o custom_option=malicious")
        assert not res["passed"]
        assert res["exit_code"] == -1
        assert "Security error" in res["output"]


# ==============================================================================
# Node-Level Unit Tests
# ==============================================================================


class TestGraphNodes:
    def test_validate_input_node_empty_task(self):
        res = validate_input_node({"task": "   "})
        assert res["status"] == "failed"
        assert len(res["errors"]) > 0

    def test_validate_input_node_valid_task(self):
        res = validate_input_node({"task": "Fix chunker overlap"})
        assert res["status"] == "validated"
        assert res["retry_count"] == 0

    def test_retrieve_context_node_insufficient_context(self):
        with patch("app.agent.nodes.search_code_semantic", return_value=[]), \
             patch("app.agent.nodes.search_code", return_value=[]):
            res = retrieve_context_node({"task": "Unknown alien component"})
            assert res["status"] == "insufficient_context"

    def test_analyze_evidence_node_passes_snippets_to_analyzer(self):
        mock_analysis = MagicMock()
        mock_analysis.status = "success"
        mock_analysis.errors = []
        mock_analysis.model_dump.return_value = {
            "task": "Test task",
            "summary": "Evidence points to issue in repo",
            "evidence": [],
            "hypotheses": [],
            "proposed_changes": [],
            "status": "success",
        }
        with patch("app.agent.nodes.analyze_code_task", return_value=mock_analysis):
            res = analyze_evidence_node({
                "task": "Test task",
                "retrieved_context": [{"file_path": "a.py", "content": "x = 1"}],
            })
            assert res["status"] == "analyzed"
            assert "summary" in res["analysis"]

    def test_propose_patch_node_no_changes_needed(self):
        state = {
            "analysis": {"proposed_changes": []}
        }
        res = propose_patch_node(state)
        assert res["status"] == "no_changes_needed"
        assert res["approval_status"] == "not_needed"
        assert res["patch"] is None

    def test_propose_patch_node_generates_diff_and_awaits_approval(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        sample = tmp_path / "foo.py"
        sample.write_text("x = 1\n", encoding="utf-8")

        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "foo.py",
                        "description": "Increment x",
                        "code_snippet": "x = 2\n",
                    }
                ]
            }
        }

        res = propose_patch_node(state)
        assert res["status"] == "awaiting_approval"
        assert res["approval_status"] == "pending"
        patch_item = res["patch"]
        assert patch_item["file_path"] == "foo.py"
        assert patch_item["file_existed_before"] is True
        assert "-x = 1" in patch_item["diff"]
        assert "+x = 2" in patch_item["diff"]

    def test_propose_patch_node_invalid_syntax_fails_and_does_not_produce_patch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        sample = tmp_path / "broken.py"
        sample.write_text("x = 1\n", encoding="utf-8")

        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "broken.py",
                        "description": "Broken syntax",
                        "code_snippet": "def invalid( syntax:\n",
                    }
                ]
            }
        }
        res = propose_patch_node(state)
        assert res["status"] == "failed"
        assert res["patch"] is None
        assert res["approval_status"] == "not_needed"
        assert any("syntax error" in e.lower() for e in res["errors"])

    def test_propose_patch_node_handles_read_failure_without_assuming_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        sample = tmp_path / "unreadable.py"
        sample.write_text("secret_code = 42\n", encoding="utf-8")

        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "unreadable.py",
                        "description": "Attempt modify",
                        "code_snippet": "new = 1\n",
                    }
                ]
            }
        }

        # Simulate read failure (e.g. PermissionError)
        with patch.object(Path, "read_text", side_effect=PermissionError("Permission denied")):
            res = propose_patch_node(state)
            assert res["status"] == "failed"
            assert res["patch"] is None
            assert any("failed to read existing file" in e.lower() for e in res["errors"])

    def test_propose_patch_node_no_op_proposal(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        sample = tmp_path / "same.py"
        sample.write_text("val = 1\n", encoding="utf-8")

        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "same.py",
                        "description": "No op",
                        "code_snippet": "val = 1\n",
                    }
                ]
            }
        }
        res = propose_patch_node(state)
        assert res["status"] == "no_changes_needed"
        assert res["patch"] is None

    def test_propose_patch_node_genuinely_new_target_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        new_file = tmp_path / "brand_new.py"
        assert not new_file.exists()

        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "brand_new.py",
                        "description": "Create new module",
                        "code_snippet": "new_code = True\n",
                    }
                ]
            }
        }
        res = propose_patch_node(state)
        assert res["status"] == "awaiting_approval"
        assert res["patch"] is not None
        assert res["patch"]["file_existed_before"] is False
        assert res["patch"]["original_content"] == ""
        assert res["patch"]["expected_original_checksum"] == compute_content_checksum("")
        assert res["patch"]["proposed_content"] == "new_code = True\n"

    def test_propose_patch_node_rejects_sensitive_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": ".env",
                        "description": "Try modifying secrets",
                        "code_snippet": "KEY=exposed\n",
                    }
                ]
            }
        }
        res = propose_patch_node(state)
        assert res["status"] == "failed"
        assert res["patch"] is None
        assert any("sensitive file" in e.lower() for e in res["errors"])

    def test_propose_patch_node_rejects_invalid_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "../../outside.py",
                        "description": "Directory traversal attempt",
                        "code_snippet": "x = 1\n",
                    }
                ]
            }
        }
        res = propose_patch_node(state)
        assert res["status"] == "failed"
        assert res["patch"] is None
        assert any("escapes repository root" in e.lower() for e in res["errors"])

    def test_apply_patch_node_refuses_when_not_approved(self):
        state = {
            "approval_status": "rejected",
            "patch": {"file_path": "a.py", "proposed_content": "x=1\n"},
        }
        res = apply_patch_node(state)
        assert res["status"] == "rejected"
        assert not res["patch_applied"]

    def test_apply_patch_node_rejects_when_missing_or_empty_patch_id(self):
        state = {
            "approval_status": "approved",
            "approved_patch_id": "",
            "patch": {"patch_id": "patch-123", "file_path": "a.py", "proposed_content": "x=1\n"},
        }
        res = apply_patch_node(state)
        assert res["status"] == "rejected"
        assert not res["patch_applied"]
        assert "missing or empty" in res["errors"][0]

    def test_apply_patch_node_rejects_when_approved_patch_id_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "calc.py"
        target.write_text("val = 10\n", encoding="utf-8")
        orig_checksum = compute_content_checksum("val = 10\n")
        actual_id = create_patch_id("calc.py", "val = 20\n", orig_checksum)

        state = {
            "approval_status": "approved",
            "approved_patch_id": "patch-different-id",
            "patch": {
                "patch_id": actual_id,
                "file_path": "calc.py",
                "proposed_content": "val = 20\n",
                "expected_original_checksum": orig_checksum,
                "proposed_checksum": compute_content_checksum("val = 20\n"),
            },
        }
        res = apply_patch_node(state)
        assert res["status"] == "rejected"
        assert not res["patch_applied"]
        assert "Patch mismatch" in res["errors"][0]
        # Target file must remain untouched
        assert target.read_text(encoding="utf-8") == "val = 10\n"

    def test_apply_patch_node_rejects_tampered_proposal_hash(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "calc.py"
        target.write_text("val = 10\n", encoding="utf-8")
        orig_checksum = compute_content_checksum("val = 10\n")
        actual_id = create_patch_id("calc.py", "val = 20\n", orig_checksum)

        state = {
            "approval_status": "approved",
            "approved_patch_id": actual_id,
            "patch": {
                "patch_id": actual_id,
                "file_path": "calc.py",
                "proposed_content": "val = 20\n",
                "expected_original_checksum": orig_checksum,
                "proposed_checksum": "forged_checksum_1234567890",
            },
        }
        res = apply_patch_node(state)
        assert res["status"] == "failed"
        assert not res["patch_applied"]
        assert "Proposal tampering detected" in res["errors"][0]

    def test_apply_patch_node_accepts_when_approved_patch_id_matches(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "calc.py"
        target.write_text("val = 10\n", encoding="utf-8")
        orig_checksum = compute_content_checksum("val = 10\n")
        actual_id = create_patch_id("calc.py", "val = 20\n", orig_checksum)

        state = {
            "approval_status": "approved",
            "approved_patch_id": actual_id,
            "patch": {
                "patch_id": actual_id,
                "file_path": "calc.py",
                "proposed_content": "val = 20\n",
                "expected_original_checksum": orig_checksum,
                "proposed_checksum": compute_content_checksum("val = 20\n"),
            },
        }
        res = apply_patch_node(state)
        assert res["status"] == "applied"
        assert res["patch_applied"]
        assert target.read_text(encoding="utf-8") == "val = 20\n"


# ==============================================================================
# Conditional Routing Tests
# ==============================================================================


class TestConditionalRouting:
    def test_route_after_validation(self):
        assert route_after_validation({"status": "failed"}) == "__end__"
        assert route_after_validation({"status": "validated"}) == "retrieve_context"

    def test_route_after_retrieval(self):
        assert route_after_retrieval({"status": "insufficient_context"}) == "__end__"
        assert route_after_retrieval({"status": "retrieved"}) == "analyze_evidence"

    def test_route_after_analysis(self):
        assert route_after_analysis({"status": "failed"}) == "__end__"
        assert route_after_analysis({"status": "analyzed"}) == "propose_patch"

    def test_route_after_propose(self):
        assert route_after_propose({"status": "no_changes_needed"}) == "__end__"
        assert route_after_propose({"status": "failed"}) == "__end__"
        assert route_after_propose({"status": "awaiting_approval"}) == "apply_patch"

    def test_route_after_apply(self):
        assert route_after_apply({"status": "rejected"}) == "handle_rejection"
        assert route_after_apply({"status": "apply_failed"}) == "__end__"
        assert route_after_apply({"status": "applied"}) == "verify_patch"

    def test_route_after_verify_passed(self):
        assert route_after_verify({"test_results": {"passed": True}}) == "__end__"

    def test_route_after_verify_retry_or_fail(self):
        # Has retries remaining -> retry
        assert route_after_verify({
            "test_results": {"passed": False},
            "retry_count": 0,
            "max_retries": 2,
        }) == "rollback_and_retry"

        # Retries exhausted -> fail
        assert route_after_verify({
            "test_results": {"passed": False},
            "retry_count": 2,
            "max_retries": 2,
        }) == "rollback_and_fail"

    def test_route_after_rollback_and_retry(self):
        assert route_after_rollback_and_retry({"status": "rollback_failed"}) == "__end__"
        assert route_after_rollback_and_retry({"status": "retrying"}) == "analyze_evidence"


# ==============================================================================
# End-to-End Graph Orchestration & Approval Boundary Tests
# ==============================================================================


class TestGraphWorkflow:
    def test_workflow_halts_at_approval_boundary_and_resumes_upon_approval(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)

        # Setup test file
        test_file = tmp_path / "service.py"
        test_file.write_text("TIMEOUT = 10\n", encoding="utf-8")

        mock_snippets = [{"file_path": "service.py", "content": "TIMEOUT = 10\n"}]
        mock_analysis = MagicMock()
        mock_analysis.status = "success"
        mock_analysis.errors = []
        mock_analysis.model_dump.return_value = {
            "task": "Increase timeout to 30",
            "summary": "Timeout needs adjustment",
            "evidence": [],
            "hypotheses": [],
            "proposed_changes": [
                {
                    "file_path": "service.py",
                    "description": "Set TIMEOUT to 30",
                    "code_snippet": "TIMEOUT = 30\n",
                }
            ],
            "status": "success",
        }

        memory = MemorySaver()
        graph = build_agent_graph(checkpointer=memory, with_approval_interrupt=True)
        config = {"configurable": {"thread_id": "session-approval-test"}}

        with patch("app.agent.nodes.search_code_semantic", return_value=mock_snippets), \
             patch("app.agent.nodes.analyze_code_task", return_value=mock_analysis), \
             patch("app.agent.nodes.run_verification_tests", return_value={"passed": True, "exit_code": 0, "output": "Tests passed"}):

            # 1. Run graph - should halt before apply_patch
            state_at_interrupt = graph.invoke(
                {"task": "Increase timeout to 30"},
                config=config,
            )

            # Assert execution paused at approval boundary
            assert state_at_interrupt["status"] == "awaiting_approval"
            assert state_at_interrupt["approval_status"] == "pending"
            assert not state_at_interrupt["patch_applied"]
            assert state_at_interrupt["patch"] is not None
            assert "+TIMEOUT = 30" in state_at_interrupt["patch"]["diff"]

            # File must NOT have been changed yet
            assert test_file.read_text(encoding="utf-8") == "TIMEOUT = 10\n"

            # 2. Check next scheduled node
            checkpoint_state = graph.get_state(config)
            assert checkpoint_state.next == ("apply_patch",)

            # 3. Supply explicit human approval with exact patch ID and resume
            patch_id = state_at_interrupt["patch"]["patch_id"]
            graph.update_state(config, {"approval_status": "approved", "approved_patch_id": patch_id})
            final_state = graph.invoke(None, config=config)

            # 4. Verify post-approval execution
            assert final_state["status"] == "verified"
            assert final_state["patch_applied"]
            assert test_file.read_text(encoding="utf-8") == "TIMEOUT = 30\n"
            assert final_state["test_results"]["passed"]

    def test_workflow_halts_and_aborts_upon_rejection(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)

        test_file = tmp_path / "config.py"
        test_file.write_text("DEBUG = False\n", encoding="utf-8")

        mock_snippets = [{"file_path": "config.py", "content": "DEBUG = False\n"}]
        mock_analysis = MagicMock()
        mock_analysis.status = "success"
        mock_analysis.errors = []
        mock_analysis.model_dump.return_value = {
            "task": "Enable debug",
            "summary": "Enable debug flag",
            "evidence": [],
            "hypotheses": [],
            "proposed_changes": [
                {
                    "file_path": "config.py",
                    "description": "Set DEBUG to True",
                    "code_snippet": "DEBUG = True\n",
                }
            ],
            "status": "success",
        }

        memory = MemorySaver()
        graph = build_agent_graph(checkpointer=memory, with_approval_interrupt=True)
        config = {"configurable": {"thread_id": "session-reject-test"}}

        with patch("app.agent.nodes.search_code_semantic", return_value=mock_snippets), \
             patch("app.agent.nodes.analyze_code_task", return_value=mock_analysis):

            # Run up to approval boundary
            state_at_interrupt = graph.invoke(
                {"task": "Enable debug"},
                config=config,
            )
            assert state_at_interrupt["status"] == "awaiting_approval"

            # Reject the proposal
            graph.update_state(config, {"approval_status": "rejected", "human_feedback": "Not permitted."})
            final_state = graph.invoke(None, config=config)

            # Must stop without writing
            assert final_state["status"] == "rejected"
            assert not final_state["patch_applied"]
            assert test_file.read_text(encoding="utf-8") == "DEBUG = False\n"

    def test_workflow_rolls_back_when_tests_fail_after_approved_patch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)

        test_file = tmp_path / "module.py"
        test_file.write_text("VALID_VALUE = 100\n", encoding="utf-8")

        mock_snippets = [{"file_path": "module.py", "content": "VALID_VALUE = 100\n"}]
        mock_analysis = MagicMock()
        mock_analysis.status = "success"
        mock_analysis.errors = []
        mock_analysis.model_dump.return_value = {
            "task": "Change value to 200",
            "summary": "Update constant",
            "evidence": [],
            "hypotheses": [],
            "proposed_changes": [
                {
                    "file_path": "module.py",
                    "description": "Set to 200",
                    "code_snippet": "VALID_VALUE = 200\n",
                }
            ],
            "status": "success",
        }

        memory = MemorySaver()
        graph = build_agent_graph(checkpointer=memory, with_approval_interrupt=True)
        config = {"configurable": {"thread_id": "session-rollback-test"}}

        with patch("app.agent.nodes.search_code_semantic", return_value=mock_snippets), \
             patch("app.agent.nodes.analyze_code_task", return_value=mock_analysis), \
             patch("app.agent.nodes.run_verification_tests", return_value={
                 "passed": False,
                 "exit_code": 1,
                 "output": "FAILED test_module.py::test_val - AssertionError: 200 != 100",
                 "test_target": "app/tests/",
             }):

            # 1. Run up to approval boundary
            state_at_interrupt = graph.invoke(
                {"task": "Change value to 200"},
                config=config,
            )
            assert state_at_interrupt["status"] == "awaiting_approval"

            # 2. Approve the patch with matching ID and max_retries set to 0 to test immediate rollback and failure
            patch_id = state_at_interrupt["patch"]["patch_id"]
            graph.update_state(config, {
                "approval_status": "approved",
                "approved_patch_id": patch_id,
                "max_retries": 0,
            })
            final_state = graph.invoke(None, config=config)

            # 3. Assert rollback occurred
            assert final_state["status"] == "verification_failed"
            assert not final_state["patch_applied"]
            # Target file on disk must have been restored to original content
            assert test_file.read_text(encoding="utf-8") == "VALID_VALUE = 100\n"
            # Preserves diff and test output in state
            assert final_state["patch"] is not None
            assert "+VALID_VALUE = 200" in final_state["patch"]["diff"]
            assert "AssertionError" in final_state["test_results"]["output"]

    def test_workflow_rollback_failure_during_retry_terminates_immediately(self, tmp_path, monkeypatch):
        """Verify that when rollback fails during retry, graph halts at rollback_failed and does NOT retry."""
        state = {
            "status": "retrying",
            "retry_count": 0,
            "max_retries": 2,
            "patch": {"file_path": "broken.py"},
            "original_file_content": "val = 1\n",
        }
        with patch("app.agent.graph.rollback_patch", return_value=(False, "Disk I/O error")):
            result = rollback_and_retry_node(state)
            assert result["status"] == "rollback_failed"
            assert result["patch_applied"] is True
            assert any("Rollback failed" in e for e in result["errors"])
            # Routing must route to END immediately
            assert route_after_rollback_and_retry(result) == "__end__"

    def test_workflow_rollback_failure_after_exhausted_retries_sets_rollback_failed(self):
        """Verify that when retries are exhausted and rollback fails, state is marked rollback_failed."""
        state = {
            "status": "retrying",
            "retry_count": 2,
            "max_retries": 2,
            "patch": {"file_path": "broken.py"},
            "original_file_content": "val = 1\n",
        }
        with patch("app.agent.graph.rollback_patch", return_value=(False, "Permission denied")):
            result = rollback_and_fail_node(state)
            assert result["status"] == "rollback_failed"
            assert result["patch_applied"] is True

    def test_verify_patch_node_handles_unexpected_exception(self):
        """Verify that an unexpected exception from the test runner triggers verification failure."""
        with patch("app.agent.nodes.run_verification_tests", side_effect=RuntimeError("Subprocess crashed")):
            res = verify_patch_node({"errors": []})
            assert res["status"] == "verification_failed"
            assert not res["test_results"]["passed"]
            assert "Subprocess crashed" in res["test_results"]["output"]


# ==============================================================================
# Multi-Edit Patching & Workflow Unit Tests
# ==============================================================================


class TestMultiEditWorkflow:
    def test_create_bundle_patch_id_deterministic(self):
        from app.agent.patch import create_bundle_patch_id
        patches = [{"patch_id": "patch-aaa"}, {"patch_id": "patch-bbb"}]
        reversed_patches = [{"patch_id": "patch-bbb"}, {"patch_id": "patch-aaa"}]
        id1 = create_bundle_patch_id(patches)
        id2 = create_bundle_patch_id(reversed_patches)
        assert id1 == id2
        assert id1.startswith("bundle-")

    def test_propose_patch_node_generates_multi_file_patch_bundle(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        file1 = tmp_path / "routes.py"
        file1.write_text("def ping(): return 'pong'\n", encoding="utf-8")
        file2 = tmp_path / "models.py"
        file2.write_text("class OldModel: pass\n", encoding="utf-8")

        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "routes.py",
                        "description": "Add health route",
                        "original_snippet": "def ping(): return 'pong'\n",
                        "code_snippet": "def ping(): return 'pong'\ndef health(): return 'ok'\n",
                    },
                    {
                        "file_path": "models.py",
                        "description": "Add new model",
                        "original_snippet": "class OldModel: pass\n",
                        "code_snippet": "class OldModel: pass\nclass NewModel: pass\n",
                    },
                ]
            }
        }

        res = propose_patch_node(state)
        assert res["status"] == "awaiting_approval"
        assert res["approval_status"] == "pending"
        assert len(res["patches"]) == 2
        assert res["bundle_patch_id"] is not None
        assert res["bundle_patch_id"].startswith("bundle-")

        # Primary patch compatibility
        assert res["patch"]["file_path"] == "routes.py"
        assert res["patches"][1]["file_path"] == "models.py"

        # Check diffs
        assert "+def health(): return 'ok'" in res["patches"][0]["diff"]
        assert "+class NewModel: pass" in res["patches"][1]["diff"]

    def test_apply_patch_node_applies_all_files_when_bundle_id_approved(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        file1 = tmp_path / "service.py"
        file1.write_text("ALPHA = 1\n", encoding="utf-8")
        file2 = tmp_path / "handler.py"
        file2.write_text("BETA = 2\n", encoding="utf-8")

        state = {
            "analysis": {
                "proposed_changes": [
                    {
                        "file_path": "service.py",
                        "description": "Update ALPHA",
                        "code_snippet": "ALPHA = 10\n",
                    },
                    {
                        "file_path": "handler.py",
                        "description": "Update BETA",
                        "code_snippet": "BETA = 20\n",
                    },
                ]
            }
        }

        prop_res = propose_patch_node(state)
        bundle_id = prop_res["bundle_patch_id"]

        apply_state = {
            **prop_res,
            "approval_status": "approved",
            "approved_patch_id": bundle_id,
        }

        apply_res = apply_patch_node(apply_state)
        assert apply_res["status"] == "applied"
        assert apply_res["patch_applied"] is True
        assert len(apply_res["applied_patches"]) == 2

        # Verify disk modifications
        assert file1.read_text(encoding="utf-8") == "ALPHA = 10\n"
        assert file2.read_text(encoding="utf-8") == "BETA = 20\n"

    def test_apply_patch_node_multi_file_transactional_rollback_on_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        file1 = tmp_path / "ok.py"
        file1.write_text("STATUS = 'init'\n", encoding="utf-8")
        orig1_checksum = compute_content_checksum("STATUS = 'init'\n")
        patch1_id = create_patch_id("ok.py", "STATUS = 'updated'\n", orig1_checksum)

        # File 2 will cause conflict (simulating concurrent edit on disk)
        file2 = tmp_path / "conflict.py"
        file2.write_text("VERSION = 1\n", encoding="utf-8")
        orig2_checksum = compute_content_checksum("VERSION = 1\n")
        patch2_id = create_patch_id("conflict.py", "VERSION = 2\n", orig2_checksum)

        # Now simulate disk conflict on file2 before applying
        file2.write_text("VERSION = 999\n", encoding="utf-8")

        patches = [
            {
                "patch_id": patch1_id,
                "file_path": "ok.py",
                "proposed_content": "STATUS = 'updated'\n",
                "expected_original_checksum": orig1_checksum,
                "proposed_checksum": compute_content_checksum("STATUS = 'updated'\n"),
            },
            {
                "patch_id": patch2_id,
                "file_path": "conflict.py",
                "proposed_content": "VERSION = 2\n",
                "expected_original_checksum": orig2_checksum,
                "proposed_checksum": compute_content_checksum("VERSION = 2\n"),
            },
        ]
        from app.agent.patch import create_bundle_patch_id
        bundle_id = create_bundle_patch_id(patches)

        state = {
            "approval_status": "approved",
            "approved_patch_id": bundle_id,
            "bundle_patch_id": bundle_id,
            "patches": patches,
            "patch": patches[0],
        }

        res = apply_patch_node(state)
        assert res["status"] == "apply_failed"
        assert not res["patch_applied"]
        # File 1 must have been rolled back to initial state!
        assert file1.read_text(encoding="utf-8") == "STATUS = 'init'\n"

    def test_workflow_multi_file_rollback_when_verification_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        file1 = tmp_path / "f1.py"
        file1.write_text("A = 1\n", encoding="utf-8")
        file2 = tmp_path / "f2.py"
        file2.write_text("B = 2\n", encoding="utf-8")

        mock_snippets = [{"file_path": "f1.py", "content": "A = 1\n"}]
        mock_analysis = MagicMock()
        mock_analysis.status = "success"
        mock_analysis.errors = []
        mock_analysis.model_dump.return_value = {
            "task": "Update both files",
            "summary": "Multi edit",
            "evidence": [],
            "hypotheses": [],
            "proposed_changes": [
                {"file_path": "f1.py", "description": "Update A", "code_snippet": "A = 100\n"},
                {"file_path": "f2.py", "description": "Update B", "code_snippet": "B = 200\n"},
            ],
            "status": "success",
        }

        memory = MemorySaver()
        graph = build_agent_graph(checkpointer=memory, with_approval_interrupt=True)
        config = {"configurable": {"thread_id": "session-multi-rollback-test"}}

        with patch("app.agent.nodes.search_code_semantic", return_value=mock_snippets), \
             patch("app.agent.nodes.analyze_code_task", return_value=mock_analysis), \
             patch("app.agent.nodes.run_verification_tests", return_value={
                 "passed": False,
                 "exit_code": 1,
                 "output": "FAILED test - multi edit verification failed",
                 "test_target": "app/tests/",
             }):

            # 1. Run to approval gate
            state_at_interrupt = graph.invoke({"task": "Update both files"}, config=config)
            assert state_at_interrupt["status"] == "awaiting_approval"
            assert len(state_at_interrupt["patches"]) == 2

            # 2. Approve with bundle ID and max_retries=0 to test immediate rollback
            bundle_id = state_at_interrupt["bundle_patch_id"]
            graph.update_state(config, {
                "approval_status": "approved",
                "approved_patch_id": bundle_id,
                "max_retries": 0,
            })
            final_state = graph.invoke(None, config=config)

            # 3. Assert verification failed and ALL files rolled back safely
            assert final_state["status"] == "verification_failed"
            assert not final_state["patch_applied"]
            assert file1.read_text(encoding="utf-8") == "A = 1\n"
            assert file2.read_text(encoding="utf-8") == "B = 2\n"

