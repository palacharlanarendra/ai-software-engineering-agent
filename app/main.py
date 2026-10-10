import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.agent.agent import (
    agent_graph,
    run_agent,
    run_agent_workflow,
    approve_and_resume_workflow,
)

app = FastAPI(
    title="AI Software Engineering Agent",
    description="Backend-first AI Software Engineering Agent with LangGraph orchestration, human approval gates, and automated test verification.",
    version="3.0.0",
)


class ChatRequest(BaseModel):
    message: str


class TaskRequest(BaseModel):
    task: str = Field(description="Natural language software engineering task")
    thread_id: Optional[str] = Field(default=None, description="Optional custom session thread ID")
    auto_approve: bool = Field(default=False, description="Automatically apply proposed patch without pausing for approval")


class ApprovalRequest(BaseModel):
    approved: bool = Field(description="True to approve and apply the patch; False to reject")
    human_feedback: Optional[str] = Field(default=None, description="Optional feedback regarding the decision")


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "AI Software Engineering Agent",
        "version": "3.0.0",
    }


@app.post("/chat")
def chat(request: ChatRequest):
    """Simple chat endpoint executing the agent workflow and returning the summary."""
    response = run_agent(request.message)
    return {
        "response": response,
    }


@app.post("/task")
def start_task(request: TaskRequest):
    """
    Initiate an agent task. Runs through validation, retrieval, analysis, and patch proposal.
    If a patch is proposed and auto_approve is False, pauses at the human approval gate.
    """
    thread_id = request.thread_id or f"task-{uuid.uuid4().hex[:8]}"
    state = run_agent_workflow(
        task=request.task,
        thread_id=thread_id,
        auto_approve=request.auto_approve,
    )

    return {
        "thread_id": thread_id,
        "state": state,
    }


@app.get("/task/{thread_id}")
def get_task_state(thread_id: str):
    """Retrieve the current state of a workflow thread."""
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = agent_graph.get_state(config)
    if not checkpoint.values:
        raise HTTPException(status_code=404, detail=f"No task found with thread_id: {thread_id}")

    return {
        "thread_id": thread_id,
        "next_nodes": checkpoint.next,
        "state": checkpoint.values,
    }


@app.post("/task/{thread_id}/approve")
def submit_approval(thread_id: str, request: ApprovalRequest):
    """
    Submit explicit human approval or rejection to resume a paused agent workflow.
    """
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = agent_graph.get_state(config)
    if not checkpoint.values:
        raise HTTPException(status_code=404, detail=f"No task found with thread_id: {thread_id}")

    final_state = approve_and_resume_workflow(
        thread_id=thread_id,
        approved=request.approved,
        human_feedback=request.human_feedback,
    )

    return {
        "thread_id": thread_id,
        "state": final_state,
    }