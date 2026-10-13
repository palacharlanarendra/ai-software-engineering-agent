import logging
import platform
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT
from app.tools.repository import list_files, read_file
from app.agent.agent import run_agent
from app.agent.service import (
    check_system_health,
    submit_task,
    get_task,
    get_task_proposal,
    submit_approval,
)
from app.schemas import (
    HealthResponse,
    ChatRequest,
    ChatResponse,
    TaskSubmitRequest,
    TaskStateResponse,
    PatchProposalResponse,
    ApprovalRequest,
    ErrorResponse,
)

from app.logger import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Software Engineering Agent",
    description=(
        "Backend-first AI Software Engineering Agent with LangGraph orchestration, "
        "semantic repository retrieval, explicit human approval gates, and automated test verification."
    ),
    version="3.0.0",
)

STATIC_DIR = PROJECT_ROOT / "app" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ==============================================================================
# Structured Exception Handlers
# ==============================================================================


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError):
    msg = str(exc).strip("'\"")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": msg, "error_code": "NOT_FOUND"},
    )


@app.exception_handler(LookupError)
async def lookup_error_handler(request: Request, exc: LookupError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "error_code": "PROPOSAL_NOT_FOUND"},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "error_code": "BAD_REQUEST"},
    )


# ==============================================================================
# Health Endpoints
# ==============================================================================


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Comprehensive system health check",
)
def get_health() -> HealthResponse:
    """Return health status including Qdrant and LLM configuration."""
    return check_system_health()


@app.get(
    "/ping",
    tags=["System"],
    summary="Simple service ping",
)
def get_ping():
    """Return simple health status including Qdrant connectivity."""
    health = check_system_health()
    return {"status": health.status, "qdrant_connected": health.qdrant_connected}


@app.get(
    "/",
    tags=["System"],
    summary="Root service health status or Cloud IDE",
)
def get_root(request: Request):
    """Return Web IDE for browsers or health status JSON for API clients."""
    if "text/html" in request.headers.get("accept", "") and (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    return check_system_health()


@app.get("/ide", include_in_schema=False)
@app.get("/demo", include_in_schema=False)
def get_ide():
    """Direct browser route to SWE Agent Cloud IDE."""
    if (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    return {"message": "IDE frontend static files not found"}


@app.get("/api/files", tags=["IDE"], summary="List repository files for Cloud IDE")
def get_repository_files() -> list[str]:
    """List active repository files filtered for IDE file tree."""
    all_files = list_files()
    filtered = [
        f for f in all_files
        if not f.startswith(".")
        and "/." not in f
        and not f.endswith(".tmp")
        and not f.endswith(".pyc")
    ]
    return sorted(filtered)


@app.get("/api/file", tags=["IDE"], summary="Read repository file for Cloud IDE")
def get_file_content(path: str):
    """Read file content safely within repository root."""
    content = read_file(path)
    if content == "Access denied.":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if content.startswith("file not found:"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=content)
    return {"path": path, "content": content}


@app.post("/api/reset", tags=["IDE"], summary="Reset repository sandbox to clean git commit")
def reset_demo_sandbox():
    """Revert files to git clean state for demo visitors."""
    try:
        subprocess.run(
            ["git", "checkout", "app/main.py", "app/schemas.py", "app/tests/test_api.py"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return {"status": "ok", "message": "Sandbox reset successfully."}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get(
    "/system/info",
    tags=["System"],
    summary="Return system and python environment information",
)
def get_system_info():
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


@app.get(
    "/version",
    tags=["System"],
    summary="Return application version and environment status",
)
def get_version():
    health = check_system_health()
    return {
        "title": app.title,
        "version": app.version,
        "status": health.status,
    }


# ==============================================================================
# Chat Endpoint
# ==============================================================================


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["Chat"],
    summary="Direct interactive agent query",
)
def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """Execute diagnostic task and return response summary."""
    answer = run_agent(request.message)
    return ChatResponse(response=answer)


# ==============================================================================
# Task Lifecycle Endpoints
# ==============================================================================


@app.post(
    "/task",
    response_model=TaskStateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Tasks"],
    summary="Submit a new engineering task",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid task description"},
    },
)
@app.post(
    "/tasks",
    response_model=TaskStateResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_task(request: TaskSubmitRequest) -> TaskStateResponse:
    """
    Submit a coding task to the agent.
    Runs intake, retrieval, analysis, and patch proposal.
    If a patch is proposed and auto_approve is False, halts at the approval gate.
    """
    return submit_task(
        task=request.task,
        thread_id=request.thread_id,
        auto_approve=request.auto_approve,
    )


@app.get(
    "/task/{thread_id}",
    response_model=TaskStateResponse,
    tags=["Tasks"],
    summary="Retrieve task execution status",
    responses={
        404: {"model": ErrorResponse, "description": "Task thread not found"},
    },
)
@app.get(
    "/tasks/{thread_id}",
    response_model=TaskStateResponse,
    include_in_schema=False,
)
def get_task_status(thread_id: str) -> TaskStateResponse:
    """Retrieve observable task state, active patch, and next scheduled graph nodes."""
    return get_task(thread_id)


@app.get(
    "/task/{thread_id}/proposal",
    response_model=PatchProposalResponse,
    tags=["Tasks"],
    summary="Inspect proposed patch diff and checksums",
    responses={
        404: {"model": ErrorResponse, "description": "Task or proposal not found"},
    },
)
@app.get(
    "/tasks/{thread_id}/proposal",
    response_model=PatchProposalResponse,
    include_in_schema=False,
)
def get_task_proposal_endpoint(thread_id: str) -> PatchProposalResponse:
    """Inspect structured patch proposal before deciding to approve or reject."""
    return get_task_proposal(thread_id)


@app.post(
    "/task/{thread_id}/approve",
    response_model=TaskStateResponse,
    tags=["Tasks"],
    summary="Approve or reject a pending code repair proposal",
    responses={
        404: {"model": ErrorResponse, "description": "Task thread not found"},
        400: {"model": ErrorResponse, "description": "Invalid approval payload"},
    },
)
@app.post(
    "/tasks/{thread_id}/approve",
    response_model=TaskStateResponse,
    include_in_schema=False,
)
def approve_task_endpoint(thread_id: str, request: ApprovalRequest) -> TaskStateResponse:
    """
    Submit explicit human approval or rejection to resume a paused agent workflow.
    Validates patch_id match, safely applies patch, and executes automated verification tests.
    """
    return submit_approval(
        thread_id=thread_id,
        approved=request.approved,
        patch_id=request.patch_id,
        human_feedback=request.human_feedback,
    )