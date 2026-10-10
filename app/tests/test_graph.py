from unittest.mock import MagicMock, patch
import pytest

from langgraph.checkpoint.memory import MemorySaver

from app.agent.state import AgentState, PatchProposal, VerificationResult
from app.agent.patch import (
    create_unified_diff,
    validate_patch_syntax,
    apply_patch_safely,
    rollback_patch,
    compute_content_checksum,
    create_patch_id,
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
    route_after_validation,
    route_after_retrieval,
    route_after_analysis,
    route_after_propose,
    route_after_apply,
    route_after_verify,
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

    def test_apply_and_rollback_patch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "hello.py"
        target.write_text("initial = True\n", encoding="utf-8")

        success, orig, err = apply_patch_safely("hello.py", "initial = False\n")
        assert success
        assert orig == "initial = True\n"
        assert target.read_text(encoding="utf-8") == "initial = False\n"

        rb_success, rb_err = rollback_patch("hello.py", orig)
        assert rb_success
        assert target.read_text(encoding="utf-8") == "initial = True\n"


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
            "summary": "Diagnosis complete",
            "evidence": [],
            "hypotheses": [],
            "proposed_changes": [],
            "status": "success",
        }

        with patch("app.agent.nodes.analyze_code_task", return_value=mock_analysis):
            res = analyze_evidence_node({
                "task": "Test task",
                "retrieved_context": [{"file_path": "a.py", "content": "x=1"}],
            })
            assert res["status"] == "analyzed"
            assert res["analysis"]["summary"] == "Diagnosis complete"

    def test_propose_patch_node_no_changes_needed(self):
        state = {
            "analysis": {"proposed_changes": []}
        }
        res = propose_patch_node(state)
        assert res["status"] == "no_changes_needed"
        assert res["approval_status"] == "not_needed"

    def test_propose_patch_node_generates_diff_and_awaits_approval(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.tools.repository.PROJECT_ROOT", tmp_path)
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
        assert "-x = 1" in patch_item["diff"]
        assert "+x = 2" in patch_item["diff"]

    def test_apply_patch_node_refuses_when_not_approved(self):
        state = {
            "approval_status": "rejected",
            "patch": {"file_path": "a.py", "proposed_content": "x=1\n"},
        }
        res = apply_patch_node(state)
        assert res["status"] == "rejected"
        assert not res["patch_applied"]

    def test_apply_patch_node_applies_when_approved(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "calc.py"
        target.write_text("val = 10\n", encoding="utf-8")

        state = {
            "approval_status": "approved",
            "patch": {"file_path": "calc.py", "proposed_content": "val = 20\n"},
        }
        res = apply_patch_node(state)
        assert res["status"] == "applied"
        assert res["patch_applied"]
        assert target.read_text(encoding="utf-8") == "val = 20\n"

    def test_apply_patch_node_rejects_when_approved_patch_id_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "calc.py"
        target.write_text("val = 10\n", encoding="utf-8")

        state = {
            "approval_status": "approved",
            "approved_patch_id": "patch-different-id",
            "patch": {
                "patch_id": "patch-actual-id",
                "file_path": "calc.py",
                "proposed_content": "val = 20\n",
            },
        }
        res = apply_patch_node(state)
        assert res["status"] == "rejected"
        assert not res["patch_applied"]
        assert "Patch mismatch" in res["errors"][0]
        # Target file must remain untouched
        assert target.read_text(encoding="utf-8") == "val = 10\n"

    def test_apply_patch_node_accepts_when_approved_patch_id_matches(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        target = tmp_path / "calc.py"
        target.write_text("val = 10\n", encoding="utf-8")

        state = {
            "approval_status": "approved",
            "approved_patch_id": "patch-123456",
            "patch": {
                "patch_id": "patch-123456",
                "file_path": "calc.py",
                "proposed_content": "val = 20\n",
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
        assert route_after_analysis({"status": "insufficient_context"}) == "__end__"
        assert route_after_analysis({"status": "failed"}) == "__end__"
        assert route_after_analysis({"status": "analyzed"}) == "propose_patch"

    def test_route_after_propose(self):
        assert route_after_propose({"status": "no_changes_needed"}) == "__end__"
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


# ==============================================================================
# End-to-End Graph Orchestration & Approval Boundary Tests
# ==============================================================================


class TestGraphWorkflow:
    def test_workflow_halts_at_approval_boundary_and_resumes_upon_approval(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("app.tools.repository.PROJECT_ROOT", tmp_path)

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

            # 3. Supply explicit human approval and resume
            graph.update_state(config, {"approval_status": "approved"})
            final_state = graph.invoke(None, config=config)

            # 4. Verify post-approval execution
            assert final_state["status"] == "verified"
            assert final_state["patch_applied"]
            assert test_file.read_text(encoding="utf-8") == "TIMEOUT = 30\n"
            assert final_state["test_results"]["passed"]

    def test_workflow_halts_and_aborts_upon_rejection(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.agent.patch.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("app.tools.repository.PROJECT_ROOT", tmp_path)

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
