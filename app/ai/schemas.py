from pydantic import BaseModel, Field


class CodeEvidence(BaseModel):
    """Specific evidence directly observed in repository code snippets."""
    file_path: str = Field(description="Relative path of the relevant file inside the repository")
    start_line: int = Field(default=1, description="Starting line number of the observed code snippet")
    end_line: int = Field(default=1, description="Ending line number of the observed code snippet")
    snippet: str = Field(description="Exact excerpt or code pattern observed")
    explanation: str = Field(description="Factual explanation of what this evidence shows")


class ProposedChange(BaseModel):
    """Specific code modification proposal."""
    file_path: str = Field(description="Target repository file to modify or create")
    description: str = Field(description="Description of what should be changed")
    rationale: str = Field(description="Why this change addresses the task or root cause")
    code_snippet: str = Field(default="", description="Proposed new or modified code snippet")


class CodeAnalysisResult(BaseModel):
    """
    Structured outcome of the AI code analysis distinguishing:
    1. Direct evidence (factual observations from repository code)
    2. Hypotheses (deductions / root-cause theories)
    3. Proposed changes (concrete code modifications)
    """
    task: str = Field(description="The user's original coding task or question")
    summary: str = Field(description="Concise diagnosis and executive summary")
    evidence: list[CodeEvidence] = Field(
        default_factory=list,
        description="Verified facts directly observed in repository snippets. Never hallucinated.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Reasoning, deductions, or root-cause explanations grounded in the evidence.",
    )
    proposed_changes: list[ProposedChange] = Field(
        default_factory=list,
        description="Concrete, actionable code modifications with target files.",
    )
    status: str = Field(
        default="success",
        description="'success' if confident, 'insufficient_context' if evidence is lacking, or 'error'",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Warnings, errors, or caveats.",
    )


class CodeAnalysisRequest(BaseModel):
    """Input payload for code analysis."""
    task: str = Field(description="The natural language task or investigation question")
    evidence_snippets: list[dict] = Field(
        default_factory=list,
        description="Retrieved code chunks or search results with file_path, start_line, end_line, and content",
    )
    additional_context: str | None = Field(
        default=None,
        description="Optional developer guidelines or additional requirements",
    )
