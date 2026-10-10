from unittest.mock import MagicMock, patch
import pytest

from app.ai.llm import get_llm
from app.ai.schemas import (
    CodeAnalysisResult,
    CodeAnalysisRequest,
    CodeEvidence,
    ProposedChange,
)
from app.ai.analyzer import (
    analyze_code_task,
    format_evidence_snippets,
)


# ==============================================================================
# Model Configuration Tests
# ==============================================================================


class TestModelConfiguration:
    def test_get_llm_success_with_explicit_key(self):
        model = get_llm(
            model="gemini-2.5-flash",
            temperature=0.2,
            timeout=45,
            max_retries=1,
            api_key="fake-test-key",
        )
        assert model.model == "gemini-2.5-flash"
        assert model.temperature == 0.2
        assert model.timeout == 45
        assert model.max_retries == 1

    def test_get_llm_missing_key_raises_clear_error(self, monkeypatch):
        monkeypatch.setattr("app.ai.llm.GEMINI_API_KEY", None)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
            get_llm(api_key=None)


# ==============================================================================
# Schema Validation Tests
# ==============================================================================


class TestSchemas:
    def test_code_analysis_result_structure(self):
        result = CodeAnalysisResult(
            task="Investigate search case sensitivity",
            summary="Search is case-insensitive using .casefold()",
            evidence=[
                CodeEvidence(
                    file_path="app/tools/repository.py",
                    start_line=83,
                    end_line=83,
                    snippet="if query.casefold() in line.casefold():",
                    explanation="Uses casefold on both query and line",
                )
            ],
            hypotheses=["The implementation was updated to use Python's casefold method."],
            proposed_changes=[
                ProposedChange(
                    file_path="app/tools/repository.py",
                    description="No changes needed",
                    rationale="Already case-insensitive",
                )
            ],
            status="success",
        )

        assert result.task == "Investigate search case sensitivity"
        assert len(result.evidence) == 1
        assert result.evidence[0].start_line == 83
        assert len(result.hypotheses) == 1
        assert len(result.proposed_changes) == 1
        assert result.status == "success"

    def test_code_analysis_request_defaults(self):
        req = CodeAnalysisRequest(task="Refactor chunker")
        assert req.task == "Refactor chunker"
        assert req.evidence_snippets == []
        assert req.additional_context is None


# ==============================================================================
# Evidence Formatting Tests
# ==============================================================================


class TestEvidenceFormatting:
    def test_format_evidence_snippets_from_dicts(self):
        snippets = [
            {
                "file_path": "app/tools/repository.py",
                "start_line": 34,
                "end_line": 37,
                "content": "if root not in path.parents:\n    return 'Access denied.'",
                "score": 0.85,
            }
        ]

        text = format_evidence_snippets(snippets)
        assert "--- Snippet 1: app/tools/repository.py (Lines 34-37) [Relevance: 0.8500] ---" in text
        assert "Access denied." in text

    def test_format_evidence_snippets_empty(self):
        assert format_evidence_snippets([]) == "No repository snippets provided."


# ==============================================================================
# Mocked Analysis Service Tests (Zero Live API Calls)
# ==============================================================================


class TestAnalyzeCodeTaskMocked:
    @pytest.fixture
    def mock_snippets(self):
        return [
            {
                "file_path": "app/tools/repository.py",
                "start_line": 34,
                "end_line": 37,
                "content": "path = (root/file_path).resolve()\nif root not in path.parents:\n    return 'Access denied.'",
                "score": 0.92,
            }
        ]

    def test_analyze_code_task_success_distinguishes_evidence_hypotheses_changes(self, mock_snippets):
        expected_result = CodeAnalysisResult(
            task="Where is path traversal prevented?",
            summary="Path traversal is checked using path.parents membership check.",
            evidence=[
                CodeEvidence(
                    file_path="app/tools/repository.py",
                    start_line=36,
                    end_line=37,
                    snippet="if root not in path.parents and path != root:\n    return 'Access denied.'",
                    explanation="Verifies resolved path stays within repository parents",
                )
            ],
            hypotheses=["The check ensures directory traversal like ../ cannot escape root."],
            proposed_changes=[
                ProposedChange(
                    file_path="app/tools/repository.py",
                    description="Keep existing traversal check",
                    rationale="Check is sound and verified",
                )
            ],
            status="success",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = expected_result
        mock_llm.with_structured_output.return_value = mock_structured

        result = analyze_code_task(
            task="Where is path traversal prevented?",
            snippets=mock_snippets,
            llm_instance=mock_llm,
        )

        assert result.status == "success"
        assert len(result.evidence) == 1
        assert result.evidence[0].file_path == "app/tools/repository.py"
        assert len(result.hypotheses) == 1
        assert len(result.proposed_changes) == 1
        mock_llm.with_structured_output.assert_called_once_with(CodeAnalysisResult)

    def test_analyze_code_task_handles_empty_task(self):
        result = analyze_code_task(task="")
        assert result.status == "error"
        assert "Empty task" in result.summary

    def test_analyze_code_task_handles_no_evidence_available(self):
        result = analyze_code_task(
            task="Find some mysterious code",
            snippets=[],
            auto_retrieve=False,
        )
        assert result.status == "insufficient_context"
        assert "No repository evidence" in result.summary

    def test_analyze_code_task_handles_model_timeout_and_api_errors(self, mock_snippets):
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = TimeoutError("Gemini API call timed out after 60s")
        mock_llm.with_structured_output.return_value = mock_structured

        result = analyze_code_task(
            task="Test timeout",
            snippets=mock_snippets,
            llm_instance=mock_llm,
        )

        assert result.status == "error"
        assert "timed out" in result.summary
        assert len(result.errors) > 0

    def test_analyze_code_task_handles_missing_llm_configuration(self, mock_snippets, monkeypatch):
        monkeypatch.setattr("app.ai.analyzer.default_llm", None)
        with patch("app.ai.analyzer.get_llm", side_effect=ValueError("No API key")):
            result = analyze_code_task(
                task="Test missing key",
                snippets=mock_snippets,
                llm_instance=None,
            )
            assert result.status == "error"
            assert "LLM service is not configured" in result.summary
