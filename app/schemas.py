from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """System health check response."""
    status: str = Field(default="ok", description="Overall health status")
    service: str = Field(default="AI Software Engineering Agent", description="Service name")
    version: str = Field(default="3.0.0", description="API version")
    qdrant_connected: bool = Field(default=False, description="Whether Qdrant vector database is reachable")
    llm_configured: bool = Field(default=False, description="Whether Gemini API key is configured")


class ChatRequest(BaseModel):
    """Simple chat query request."""
    message: str = Field(..., min_length=1, description="Natural language question or command")


class ChatResponse(BaseModel):
    """Simple chat response."""
    response: str = Field(description="Agent diagnostic response or answer")


class TaskSubmitRequest(BaseModel):
    """Request to initiate a new software engineering task."""
    task: str = Field(..., min_length=1, description="Natural language software engineering task description")
    thread_id: Optional[str] = Field(default=None, description="Optional custom session thread ID")
    auto_approve: bool = Field(default=False, description="Automatically apply proposed patch without pausing for approval")


class ApprovalRequest(BaseModel):
    """Request to approve or reject a proposed code modification."""
    approved: bool = Field(..., description="True to approve and apply the patch; False to reject")
    patch_id: Optional[str] = Field(default=None, description="Exact patch ID being approved to prevent mismatched changes")
    human_feedback: Optional[str] = Field(default=None, description="Optional human feedback explaining the decision")


class PatchProposalResponse(BaseModel):
    """Structured proposal for a repository file modification."""
    patch_id: str = Field(description="Unique, tamper-evident patch identifier")
    file_path: str = Field(description="Target repository file path")
    description: str = Field(description="Explanation of the proposed change")
    diff: str = Field(description="Unified diff of the proposed changes")
    original_content: str = Field(description="Original file content before editing")
    proposed_content: str = Field(description="Proposed file content")
    expected_original_checksum: str = Field(description="SHA256 checksum of original content")
    proposed_checksum: str = Field(description="SHA256 checksum of proposed content")


class VerificationResultResponse(BaseModel):
    """Result of constrained automated verification tests."""
    passed: bool = Field(description="Whether all verification tests passed")
    exit_code: int = Field(description="Process exit code of test runner")
    output: str = Field(description="Captured stdout and stderr of test runner")
    test_target: Optional[str] = Field(default=None, description="Target test directory or file")


class TaskStateResponse(BaseModel):
    """Full observable state of an engineering task lifecycle."""
    thread_id: str = Field(description="Unique session thread identifier")
    task: str = Field(description="Task description")
    status: str = Field(description="Current workflow status")
    approval_status: str = Field(default="not_needed", description="Approval gate status (pending, approved, rejected, not_needed)")
    next_nodes: List[str] = Field(default_factory=list, description="Next nodes scheduled to execute in LangGraph")
    patch_applied: bool = Field(default=False, description="Whether patch has been applied to disk")
    patch: Optional[PatchProposalResponse] = Field(default=None, description="Active patch proposal if any")
    test_results: Optional[VerificationResultResponse] = Field(default=None, description="Automated test verification results if run")
    retry_count: int = Field(default=0, description="Number of verification retries attempted")
    errors: List[str] = Field(default_factory=list, description="List of recorded error messages")


class ErrorResponse(BaseModel):
    """Standard structured error response."""
    detail: str = Field(description="Human-readable error explanation")
    error_code: str = Field(description="Machine-readable error classification code")
