from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pytest

from app.main import app

client = TestClient(app)


def test_health_check_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "AI Software Engineering Agent"


def test_chat_endpoint():
    with patch("app.main.run_agent", return_value="Repository analysis summary"):
        response = client.post("/chat", json={"message": "Where is search handled?"})
        assert response.status_code == 200
        assert response.json()["response"] == "Repository analysis summary"


def test_start_task_pauses_for_approval():
    mock_state = {
        "task": "Fix bug",
        "status": "awaiting_approval",
        "approval_status": "pending",
        "patch": {
            "file_path": "fix.py",
            "diff": "--- a/fix.py\n+++ b/fix.py\n+fixed=True\n",
        },
    }

    with patch("app.main.run_agent_workflow", return_value=mock_state):
        response = client.post("/task", json={"task": "Fix bug", "thread_id": "test-thread-1"})
        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "test-thread-1"
        assert data["state"]["status"] == "awaiting_approval"
        assert data["state"]["patch"]["file_path"] == "fix.py"


def test_approve_task_resumes_workflow():
    mock_final_state = {
        "status": "verified",
        "approval_status": "approved",
        "patch_applied": True,
        "test_results": {"passed": True, "exit_code": 0, "output": "Tests passed"},
    }

    # Mock checkpoint state existing
    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {"status": "awaiting_approval"}

    with patch.object(app.extra.get("agent_graph") or __import__("app.main").main.agent_graph, "get_state", return_value=mock_checkpoint), \
         patch("app.main.approve_and_resume_workflow", return_value=mock_final_state):
        response = client.post("/task/test-thread-1/approve", json={"approved": True})
        assert response.status_code == 200
        data = response.json()
        assert data["state"]["status"] == "verified"
        assert data["state"]["patch_applied"] is True


def test_approve_task_not_found():
    mock_checkpoint = MagicMock()
    mock_checkpoint.values = {}

    with patch.object(__import__("app.main").main.agent_graph, "get_state", return_value=mock_checkpoint):
        response = client.post("/task/non-existent-thread/approve", json={"approved": True})
        assert response.status_code == 404
