from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.schemas import TaskStateResponse, PatchProposalResponse

client = TestClient(app)


def test_health_check_endpoints():
    """Verify both / and /health return 200 with structured health details."""
    for path in ["/", "/health"]:
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "degraded"]
        assert data["service"] == "AI Software Engineering Agent"
        assert data["version"] == "3.0.0"
        assert "qdrant_connected" in data
        assert "llm_configured" in data


def test_chat_endpoint():
    """Verify chat endpoint returns diagnostic answer."""
    with patch("app.main.run_agent", return_value="Repository analysis summary"):
        response = client.post("/chat", json={"message": "Where is search handled?"})
        assert response.status_code == 200
        assert response.json()["response"] == "Repository analysis summary"


def test_start_task_pauses_for_approval():
    """Verify task intake starts workflow, returns 201, and halts at approval gate."""
    mock_state = {
        "task": "Fix bug",
        "status": "awaiting_approval",
        "approval_status": "pending",
        "patch_applied": False,
        "patch": {
            "patch_id": "patch-123456",
            "file_path": "fix.py",
            "description": "Fix bug description",
            "diff": "--- a/fix.py\n+++ b/fix.py\n+fixed=True\n",
            "original_content": "",
            "proposed_content": "fixed=True\n",
            "expected_original_checksum": "e3b0c44298fc1c14",
            "proposed_checksum": "abc12345def67890",
        },
    }

    mock_checkpoint = MagicMock()
    mock_checkpoint.values = mock_state
    mock_checkpoint.next = ["apply_patch"]

    with patch("app.agent.service.run_agent_workflow", return_value=mock_state), \
         patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint):
        response = client.post("/task", json={"task": "Fix bug", "thread_id": "test-thread-1"})
        assert response.status_code == 201
        data = response.json()
        assert data["thread_id"] == "test-thread-1"
        assert data["status"] == "awaiting_approval"
        assert data["approval_status"] == "pending"
        assert data["patch"]["file_path"] == "fix.py"
        assert data["patch"]["patch_id"] == "patch-123456"
        assert data["next_nodes"] == ["apply_patch"]


def test_start_task_rejects_empty_description():
    """Verify submitting an empty or whitespace task description returns 400 Bad Request or 422."""
    response = client.post("/task", json={"task": "   ", "thread_id": "empty-task"})
    assert response.status_code in [400, 422]
    data = response.json()
    assert "detail" in data


def test_get_task_state_success():
    """Verify inspecting task execution state returns 200 with full lifecycle data."""
    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {
        "task": "Fix bug",
        "status": "awaiting_approval",
        "approval_status": "pending",
        "patch_applied": False,
    }
    mock_checkpoint.next = ["apply_patch"]

    with patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint):
        response = client.get("/task/test-thread-1")
        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "test-thread-1"
        assert data["next_nodes"] == ["apply_patch"]
        assert data["status"] == "awaiting_approval"


def test_get_task_state_not_found():
    """Verify requesting a non-existent thread returns 404 with structured error envelope."""
    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {}

    with patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint):
        response = client.get("/task/non-existent-thread")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
        assert data["error_code"] == "NOT_FOUND"


def test_get_task_proposal_success():
    """Verify dedicated proposal inspection endpoint returns the active patch proposal."""
    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {
        "task": "Fix bug",
        "status": "awaiting_approval",
        "patch": {
            "patch_id": "patch-xyz789",
            "file_path": "app/tools/repository.py",
            "description": "Improve docstring",
            "diff": "--- a/app/tools/repository.py\n+++ b/app/tools/repository.py\n",
            "original_content": "# old",
            "proposed_content": "# new",
            "expected_original_checksum": "1111222233334444",
            "proposed_checksum": "5555666677778888",
        },
    }
    mock_checkpoint.next = ["apply_patch"]

    with patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint):
        response = client.get("/task/test-thread-1/proposal")
        assert response.status_code == 200
        data = response.json()
        assert data["patch_id"] == "patch-xyz789"
        assert data["file_path"] == "app/tools/repository.py"
        assert "Improve docstring" in data["description"]
        assert data["expected_original_checksum"] == "1111222233334444"


def test_get_task_proposal_not_found_when_no_patch_exists():
    """Verify requesting proposal when none exists returns 404."""
    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {
        "task": "Analyze codebase",
        "status": "no_changes_needed",
        "patch": None,
    }
    mock_checkpoint.next = []

    with patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint):
        response = client.get("/task/test-thread-1/proposal")
        assert response.status_code == 404
        data = response.json()
        assert "no patch proposal" in data["detail"].lower()
        assert data["error_code"] == "PROPOSAL_NOT_FOUND"


def test_approve_task_resumes_workflow():
    """Verify submitting approval applies the patch and executes verification tests."""
    mock_final_state = {
        "task": "Fix bug",
        "status": "verified",
        "approval_status": "approved",
        "approved_patch_id": "patch-123456",
        "patch_applied": True,
        "test_results": {"passed": True, "exit_code": 0, "output": "Tests passed", "test_target": "app/tests/"},
    }

    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {"status": "awaiting_approval"}

    with patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint), \
         patch("app.agent.service.approve_and_resume_workflow", return_value=mock_final_state) as mock_resume:
        response = client.post(
            "/task/test-thread-1/approve",
            json={"approved": True, "patch_id": "patch-123456", "human_feedback": "Approved for release"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "verified"
        assert data["patch_applied"] is True
        assert data["test_results"]["passed"] is True
        mock_resume.assert_called_once_with(
            thread_id="test-thread-1",
            approved=True,
            patch_id="patch-123456",
            human_feedback="Approved for release",
        )


def test_reject_task_resumes_workflow():
    """Verify submitting rejection aborts workflow and leaves repository untouched."""
    mock_final_state = {
        "task": "Fix bug",
        "status": "rejected",
        "approval_status": "rejected",
        "patch_applied": False,
        "human_feedback": "Not approved",
    }

    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {"status": "awaiting_approval"}

    with patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint), \
         patch("app.agent.service.approve_and_resume_workflow", return_value=mock_final_state) as mock_resume:
        response = client.post(
            "/task/test-thread-1/approve",
            json={"approved": False, "human_feedback": "Not approved"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert data["patch_applied"] is False


def test_approve_task_not_found():
    """Verify attempting to approve non-existent task returns 404."""
    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {}

    with patch("app.agent.service.agent_graph.get_state", return_value=mock_checkpoint):
        response = client.post("/task/non-existent-thread/approve", json={"approved": True})
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
        assert data["error_code"] == "NOT_FOUND"
