import logging
from typing import Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from app.agent.state import AgentState
from app.agent.patch import rollback_patch
from app.agent.nodes import (
    validate_input_node,
    retrieve_context_node,
    analyze_evidence_node,
    propose_patch_node,
    apply_patch_node,
    verify_patch_node,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Helper Nodes for Retry and Rollback
# ==============================================================================


def rollback_and_retry_node(state: AgentState) -> dict:
    """Roll back previous patch before making a bounded retry attempt."""
    patch = state.get("patch")
    orig = state.get("original_file_content")
    if patch and orig is not None:
        rollback_patch(patch["file_path"], orig)

    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "patch_applied": False,
        "status": "retrying",
    }


def rollback_and_fail_node(state: AgentState) -> dict:
    """Roll back modified file when verification fails and retries are exhausted."""
    patch = state.get("patch")
    orig = state.get("original_file_content")
    if patch and orig is not None:
        rollback_patch(patch["file_path"], orig)

    return {
        "patch_applied": False,
        "status": "verification_failed",
    }


def handle_rejection_node(state: AgentState) -> dict:
    """Handle human rejection of proposed patch."""
    return {
        "status": "rejected",
        "patch_applied": False,
    }


# ==============================================================================
# Conditional Routing Functions
# ==============================================================================


def route_after_validation(state: AgentState) -> Literal["retrieve_context", "__end__"]:
    if state.get("status") == "failed":
        return "__end__"
    return "retrieve_context"


def route_after_retrieval(state: AgentState) -> Literal["analyze_evidence", "__end__"]:
    if state.get("status") == "insufficient_context":
        return "__end__"
    return "analyze_evidence"


def route_after_analysis(state: AgentState) -> Literal["propose_patch", "__end__"]:
    if state.get("status") in ["insufficient_context", "failed"]:
        return "__end__"
    return "propose_patch"


def route_after_propose(state: AgentState) -> Literal["apply_patch", "__end__"]:
    if state.get("status") == "no_changes_needed":
        return "__end__"
    return "apply_patch"


def route_after_apply(state: AgentState) -> Literal["verify_patch", "handle_rejection", "__end__"]:
    status = state.get("status")
    if status == "rejected":
        return "handle_rejection"
    if status == "apply_failed":
        return "__end__"
    return "verify_patch"


def route_after_verify(state: AgentState) -> Literal["rollback_and_retry", "rollback_and_fail", "__end__"]:
    test_res = state.get("test_results") or {}
    if test_res.get("passed", False):
        return "__end__"

    retries = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)
    if retries < max_retries:
        return "rollback_and_retry"

    return "rollback_and_fail"


# ==============================================================================
# Graph Builder
# ==============================================================================


def build_agent_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    with_approval_interrupt: bool = True,
):
    """
    Construct the LangGraph state machine with explicit nodes, observable transitions,
    conditional routing, bounded retries, and human approval interrupts.

    Args:
        checkpointer: State checkpointer for pausing and resuming across requests.
        with_approval_interrupt: If True, halts immediately before apply_patch to await human approval.

    Returns:
        Compiled LangGraph instance.
    """
    builder = StateGraph(AgentState)

    # Add explicit nodes
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("retrieve_context", retrieve_context_node)
    builder.add_node("analyze_evidence", analyze_evidence_node)
    builder.add_node("propose_patch", propose_patch_node)
    builder.add_node("apply_patch", apply_patch_node)
    builder.add_node("verify_patch", verify_patch_node)
    builder.add_node("handle_rejection", handle_rejection_node)
    builder.add_node("rollback_and_retry", rollback_and_retry_node)
    builder.add_node("rollback_and_fail", rollback_and_fail_node)

    # Add edges and conditional routing
    builder.add_edge(START, "validate_input")

    builder.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {
            "retrieve_context": "retrieve_context",
            "__end__": END,
        },
    )

    builder.add_conditional_edges(
        "retrieve_context",
        route_after_retrieval,
        {
            "analyze_evidence": "analyze_evidence",
            "__end__": END,
        },
    )

    builder.add_conditional_edges(
        "analyze_evidence",
        route_after_analysis,
        {
            "propose_patch": "propose_patch",
            "__end__": END,
        },
    )

    builder.add_conditional_edges(
        "propose_patch",
        route_after_propose,
        {
            "apply_patch": "apply_patch",
            "__end__": END,
        },
    )

    builder.add_conditional_edges(
        "apply_patch",
        route_after_apply,
        {
            "verify_patch": "verify_patch",
            "handle_rejection": "handle_rejection",
            "__end__": END,
        },
    )

    builder.add_edge("handle_rejection", END)

    builder.add_conditional_edges(
        "verify_patch",
        route_after_verify,
        {
            "rollback_and_retry": "rollback_and_retry",
            "rollback_and_fail": "rollback_and_fail",
            "__end__": END,
        },
    )

    # Bounded retry loop: route back to analyze_evidence
    builder.add_edge("rollback_and_retry", "analyze_evidence")
    builder.add_edge("rollback_and_fail", END)

    # Compile with checkpointing and approval interrupt
    chk = checkpointer if checkpointer is not None else MemorySaver()
    interrupts = ["apply_patch"] if with_approval_interrupt else []

    return builder.compile(
        checkpointer=chk,
        interrupt_before=interrupts,
    )
