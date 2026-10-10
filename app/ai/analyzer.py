import logging
from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.ai.llm import get_llm, llm as default_llm
from app.ai.schemas import CodeAnalysisResult, CodeAnalysisRequest, ProposedChange, CodeEvidence
from app.rag.retriever import search_code_semantic

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are an expert AI software engineering analyst and diagnostic engine.
Your role is to analyze a coding task using ONLY the repository evidence snippets provided.

You must strictly categorize your analysis into three distinct components:
1. EVIDENCE: Factual, verifiable code details observed directly in the provided snippets.
   - Quote exact snippets, line numbers, and file paths.
   - Never hallucinate files, functions, or lines not present in the snippets.
2. HYPOTHESES: Logical deductions, root causes, or architectural explanations.
   - Clearly explain why the system behaves as it does based on the evidence.
3. PROPOSED CHANGES: Concrete, actionable code modifications addressing the task.
   - Identify target files and propose minimal, precise fixes or additions.

If the provided evidence is completely insufficient to address the task:
- Set status to 'insufficient_context'.
- State clearly what context is missing in the summary.
- Do NOT guess or hallucinate imaginary code.
"""

ANALYSIS_HUMAN_PROMPT = """Coding Task:
{task}

{additional_context}

Repository Evidence Snippets:
{evidence_text}
"""

analysis_prompt_template = ChatPromptTemplate.from_messages([
    ("system", ANALYSIS_SYSTEM_PROMPT),
    ("human", ANALYSIS_HUMAN_PROMPT),
])


def format_evidence_snippets(snippets: list[dict | Any]) -> str:
    """Format retrieved repository snippets into clear text for LLM evidence analysis."""
    if not snippets:
        return "No repository snippets provided."

    formatted_parts = []
    for index, item in enumerate(snippets, start=1):
        if isinstance(item, dict):
            file_path = item.get("file_path") or item.get("file") or "unknown"
            start_line = item.get("start_line", 1)
            end_line = item.get("end_line", 1)
            content = item.get("content", "")
            score = item.get("score")
        else:
            file_path = getattr(item, "file_path", "unknown")
            start_line = getattr(item, "start_line", 1)
            end_line = getattr(item, "end_line", 1)
            content = getattr(item, "content", "")
            score = getattr(item, "score", None)

        score_str = f" [Relevance: {score:.4f}]" if score is not None else ""
        formatted_parts.append(
            f"--- Snippet {index}: {file_path} (Lines {start_line}-{end_line}){score_str} ---\n{content}\n"
        )

    return "\n".join(formatted_parts)


def analyze_code_task(
    task: str,
    snippets: list[dict | Any] | None = None,
    additional_context: str | None = None,
    llm_instance: BaseChatModel | None = None,
    auto_retrieve: bool = True,
    retrieval_limit: int = 5,
) -> CodeAnalysisResult:
    """
    Analyze a coding task using retrieved repository evidence and structured LLM output.

    Args:
        task: Natural language coding task or question.
        snippets: Optional list of retrieved code snippets. If None and auto_retrieve=True,
                  semantic search is automatically executed.
        additional_context: Optional developer constraints or notes.
        llm_instance: Optional LangChain chat model. Defaults to centralized Gemini model.
        auto_retrieve: If True and snippets is None, retrieves context from Qdrant.
        retrieval_limit: Number of chunks to retrieve if auto_retrieve is used.

    Returns:
        Structured CodeAnalysisResult distinguishing evidence, hypotheses, and proposed changes.
    """
    if not task or not task.strip():
        return CodeAnalysisResult(
            task="",
            summary="Empty task provided. Please specify a coding question or investigation goal.",
            status="error",
            errors=["Task description cannot be empty."],
        )

    # 1. Resolve repository context snippets
    evidence_snippets = snippets
    if evidence_snippets is None and auto_retrieve:
        try:
            evidence_snippets = search_code_semantic(task, limit=retrieval_limit)
        except Exception as exc:
            logger.warning(f"Auto-retrieval failed: {exc}")
            evidence_snippets = []

    if not evidence_snippets:
        return CodeAnalysisResult(
            task=task,
            summary="No repository evidence was found to analyze this task.",
            status="insufficient_context",
            errors=["No matching repository snippets were found."],
        )

    # 2. Resolve LLM instance
    model = llm_instance or default_llm
    if model is None:
        try:
            model = get_llm()
        except ValueError as err:
            return CodeAnalysisResult(
                task=task,
                summary="LLM service is not configured.",
                status="error",
                errors=[str(err)],
            )

    # 3. Format input for structured generation
    evidence_text = format_evidence_snippets(evidence_snippets)
    extra_context_str = f"Additional Developer Instructions:\n{additional_context}\n" if additional_context else ""

    formatted_messages = analysis_prompt_template.format_messages(
        task=task,
        additional_context=extra_context_str,
        evidence_text=evidence_text,
    )

    # 4. Invoke LLM with structured output parsing & error handling
    try:
        structured_model = model.with_structured_output(CodeAnalysisResult)
        result = structured_model.invoke(formatted_messages)

        if isinstance(result, CodeAnalysisResult):
            # Ensure task field is preserved
            result.task = task
            return result

        if isinstance(result, dict):
            result["task"] = task
            return CodeAnalysisResult(**result)

        return CodeAnalysisResult(
            task=task,
            summary=str(result),
            status="success",
        )

    except Exception as exc:
        logger.error(f"Code analysis failed: {exc}", exc_info=True)
        return CodeAnalysisResult(
            task=task,
            summary=f"Analysis encountered an error during model invocation: {exc}",
            status="error",
            errors=[str(exc)],
        )
