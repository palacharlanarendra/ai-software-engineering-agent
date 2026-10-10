import logging
import os
import uuid
from typing import Optional

from app.agent.agent import (
    agent_graph,
    run_agent_workflow,
    approve_and_resume_workflow,
)
from app.rag.vector_store import get_qdrant_client
from app.schemas import (
    HealthResponse,
    TaskStateResponse,
    PatchProposalResponse,
    VerificationResultResponse,
)

logger = logging.getLogger(__name__)


def check_system_health() -> HealthResponse:
    """Check connectivity to system dependencies including Qdrant and LLM configuration."""
    qdrant_ok = False
    try:
        client = get_qdrant_client()
        client.get_collections()
        qdrant_ok = True
    except Exception as exc:
        logger.warning(f"Health check: Qdrant unreachable: {exc}")

    llm_ok = bool(os.getenv("GEMINI_API_KEY"))

    return HealthResponse(
        status="ok" if qdrant_ok and llm_ok else "degraded",
        service="AI Software Engineering Agent",
        version="3.0.0",
        qdrant_connected=qdrant_ok,
        llm_configured=llm_ok,
    )


def _format_task_state(thread_id: str, state_values: dict, next_nodes: list[str]) -> TaskStateResponse:
    """Format LangGraph state dictionary into typed TaskStateResponse schema."""
    patch_data = state_values.get("patch")
    patch_model = None
    if patch_data and isinstance(patch_data, dict):
        patch_model = PatchProposalResponse(
            patch_id=patch_data.get("patch_id", ""),
            file_path=patch_data.get("file_path", ""),
            description=patch_data.get("description", ""),
            diff=patch_data.get("diff", ""),
            original_content=patch_data.get("original_content", ""),
            proposed_content=patch_data.get("proposed_content", ""),
            expected_original_checksum=patch_data.get("expected_original_checksum", ""),
            proposed_checksum=patch_data.get("proposed_checksum", ""),
        )

    verify_data = state_values.get("test_results")
    verify_model = None
    if verify_data and isinstance(verify_data, dict):
        verify_model = VerificationResultResponse(
            passed=verify_data.get("passed", False),
            exit_code=verify_data.get("exit_code", -1),
            output=verify_data.get("output", ""),
            test_target=verify_data.get("test_target"),
        )

    return TaskStateResponse(
        thread_id=thread_id,
        task=state_values.get("task", ""),
        status=state_values.get("status", "unknown"),
        approval_status=state_values.get("approval_status", "not_needed"),
        next_nodes=next_nodes,
        patch_applied=state_values.get("patch_applied", False),
        patch=patch_model,
        test_results=verify_model,
        retry_count=state_values.get("retry_count", 0),
        errors=state_values.get("errors", []),
    )


def submit_task(
    task: str,
    thread_id: Optional[str] = None,
    auto_approve: bool = False,
) -> TaskStateResponse:
    """
    Initiate a new software engineering task through the LangGraph workflow.
    Executes through intake, retrieval, analysis, and patch proposal, halting
    before disk changes if a patch is proposed and auto_approve is False.
    """
    if not task or not task.strip():
        raise ValueError("Task description cannot be empty.")

    session_id = thread_id or f"task-{uuid.uuid4().hex[:8]}"
    state_values = run_agent_workflow(
        task=task.strip(),
        thread_id=session_id,
        auto_approve=auto_approve,
    )

    config = {"configurable": {"thread_id": session_id}}
    checkpoint = agent_graph.get_state(config)
    next_nodes = list(checkpoint.next) if checkpoint else []

    return _format_task_state(session_id, state_values, next_nodes)


def get_task(thread_id: str) -> TaskStateResponse:
    """Retrieve full execution state and scheduled nodes for a task."""
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = agent_graph.get_state(config)
    if not checkpoint or not checkpoint.values:
        raise KeyError(f"Task with thread_id '{thread_id}' not found.")

    next_nodes = list(checkpoint.next) if checkpoint else []
    return _format_task_state(thread_id, checkpoint.values, next_nodes)


def get_task_proposal(thread_id: str) -> PatchProposalResponse:
    """Retrieve the pending structured patch proposal for inspection."""
    task_state = get_task(thread_id)
    if not task_state.patch:
        raise LookupError(f"No patch proposal exists for task '{thread_id}'.")
    return task_state.patch


def submit_approval(
    thread_id: str,
    approved: bool,
    patch_id: Optional[str] = None,
    human_feedback: Optional[str] = None,
) -> TaskStateResponse:
    """
    Submit explicit human approval or rejection to resume a paused agent workflow.
    """
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = agent_graph.get_state(config)
    if not checkpoint or not checkpoint.values:
        raise KeyError(f"Task with thread_id '{thread_id}' not found.")

    final_state = approve_and_resume_workflow(
        thread_id=thread_id,
        approved=approved,
        patch_id=patch_id,
        human_feedback=human_feedback,
    )

    post_checkpoint = agent_graph.get_state(config)
    next_nodes = list(post_checkpoint.next) if post_checkpoint else []

    return _format_task_state(thread_id, final_state, next_nodes)
