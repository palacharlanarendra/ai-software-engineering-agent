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
    file_existed_before: bool


class VerificationResult(TypedDict, total=False):
    """Result of constrained automated verification tests."""
    passed: bool
    exit_code: int
    output: str
    test_target: Optional[str]


class AgentState(TypedDict, total=False):
    """
    Observable state schema for the Software Engineering Agent graph.
    Tracks the full lifecycle from task intake through multi-edit patching,
    explicit approval, verification, and transactional rollback.
    """
    task: str
    retrieved_context: List[Dict[str, Any]]
    investigation_notes: List[Dict[str, Any]]
    analysis: Optional[Dict[str, Any]]
    patches: List[PatchProposal]                 # Multi-edit: all proposed file modifications
    patch: Optional[PatchProposal]               # Primary/first patch for single-edit compatibility
    bundle_patch_id: Optional[str]               # Aggregate changeset ID covering all patches
    approval_status: str  # "pending", "approved", "rejected", "not_needed"
    approved_patch_id: Optional[str]
    human_feedback: Optional[str]
    patch_applied: bool
    applied_patches: List[Dict[str, Any]]        # Record of successfully applied file patches
    original_file_content: Optional[str]         # Baseline content of primary target file
    original_file_contents: Dict[str, str]       # Multi-file baseline content map {file_path: content}
    file_existed_before: Optional[bool]          # Existence flag of primary target file
    files_existed_before: Dict[str, bool]        # Multi-file existence map {file_path: existed}
    expected_applied_checksum: Optional[str]     # Checksum of applied primary content
    expected_applied_checksums: Dict[str, str]   # Multi-file checksum map {file_path: checksum}
    test_results: Optional[VerificationResult]
    retry_count: int
    max_retries: int
    status: str
    errors: List[str]


