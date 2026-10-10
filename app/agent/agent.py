import logging
import uuid
from typing import Optional

from app.agent.graph import build_agent_graph
from app.agent.state import AgentState

logger = logging.getLogger(__name__)

# Primary compiled LangGraph workflow instance
agent_graph = build_agent_graph()


def run_agent_workflow(
    task: str,
    thread_id: Optional[str] = None,
    auto_approve: bool = False,
) -> AgentState:
    """
    Execute the Software Engineering Agent workflow.

    Args:
        task: Natural language coding task.
        thread_id: Unique session identifier for checkpointer state persistence.
        auto_approve: If True, automatically approves proposed patch without pausing.

    Returns:
        AgentState at the current workflow checkpoint (either paused at approval or finished).
    """
    session_id = thread_id or f"session-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": session_id}}

    # Initial graph execution up to approval boundary
    state: AgentState = agent_graph.invoke({"task": task}, config=config)

    # If auto-approval is enabled and graph is awaiting approval, approve and resume
    if auto_approve and state.get("status") == "awaiting_approval":
        agent_graph.update_state(config, {"approval_status": "approved"})
        state = agent_graph.invoke(None, config=config)

    return state


def approve_and_resume_workflow(
    thread_id: str,
    approved: bool = True,
    patch_id: Optional[str] = None,
    human_feedback: Optional[str] = None,
) -> AgentState:
    """
    Resume an agent workflow that is halted at the human approval boundary.

    Args:
        thread_id: Active session identifier.
        approved: True to apply patch and verify; False to reject and abort.
        patch_id: Optional exact patch ID tied to the approval.
        human_feedback: Optional feedback explaining rejection or instructions.

    Returns:
        Final AgentState after executing post-approval stages.
    """
    config = {"configurable": {"thread_id": thread_id}}
    status_str = "approved" if approved else "rejected"

    update_payload = {"approval_status": status_str}
    if patch_id:
        update_payload["approved_patch_id"] = patch_id
    if human_feedback:
        update_payload["human_feedback"] = human_feedback

    agent_graph.update_state(config, update_payload)
    return agent_graph.invoke(None, config=config)


def run_agent(question: str) -> str:
    """
    Legacy convenience interface returning a summary answer string.
    """
    state = run_agent_workflow(question, auto_approve=False)
    analysis = state.get("analysis")
    if analysis and "summary" in analysis:
        return analysis["summary"]
    return state.get("status", "completed")


if __name__ == "__main__":
    task_example = "Where is repository path traversal handled?"
    print(f"Running task: {task_example}")
    result_state = run_agent_workflow(task_example)
    print("\nWorkflow status:", result_state.get("status"))
    if result_state.get("analysis"):
        print("Diagnosis Summary:\n", result_state["analysis"].get("summary"))