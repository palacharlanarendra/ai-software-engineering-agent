from typing import Any, Dict, List, Optional, TypedDict


class PatchProposal(TypedDict, total=False):
    """Structured proposal for a repository file modification."""
    patch_id: str
    file_path: str
    description: str
    diff: str
    original_content: str
    proposed_content: str
    expected_original_checksum: str
    proposed_checksum: str


class VerificationResult(TypedDict, total=False):
    """Result of constrained automated verification tests."""
    passed: bool
    exit_code: int
    output: str
    test_target: Optional[str]


class AgentState(TypedDict, total=False):
    """
    Observable state schema for the Software Engineering Agent graph.
    Tracks the full lifecycle from task intake through verification.
    """
    task: str
    retrieved_context: List[Dict[str, Any]]
    analysis: Optional[Dict[str, Any]]
    patch: Optional[PatchProposal]
    approval_status: str  # "pending", "approved", "rejected", "not_needed"
    approved_patch_id: Optional[str]
    human_feedback: Optional[str]
    patch_applied: bool
    original_file_content: Optional[str]
    test_results: Optional[VerificationResult]
    retry_count: int
    max_retries: int
    status: str
    errors: List[str]
