from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import (
    IGNORED_DIRS,
    SENSITIVE_FILES,
    EMBEDDING_DIMENSION,
)
from app.rag.chunker import chunk_code, CodeChunk
from app.rag.indexer import index_file, index_repository
from app.rag.retriever import search_code_semantic, SemanticSearchResult
from app.rag.vector_store import ensure_collection


# ==============================================================================
# Chunking Tests
# ==============================================================================


class TestChunkCode:
    def test_chunk_code_basic_structure(self):
        sample_code = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"
        chunks = chunk_code(sample_code, "test/sample.py", chunk_size=5, overlap=2)

        assert len(chunks) == 3
        first_chunk = chunks[0]
        assert isinstance(first_chunk, CodeChunk)
        assert first_chunk.file_path == "test/sample.py"
        assert first_chunk.chunk_index == 0
        assert first_chunk.start_line == 1
        assert first_chunk.end_line == 5
        assert first_chunk.content == "line1\nline2\nline3\nline4\nline5"

        second_chunk = chunks[1]
        assert second_chunk.chunk_index == 1
        assert second_chunk.start_line == 4
        assert second_chunk.end_line == 8

        third_chunk = chunks[2]
        assert third_chunk.chunk_index == 2
        assert third_chunk.start_line == 7
        assert third_chunk.end_line == 10

    def test_chunk_code_single_chunk_when_content_fits(self):
        content = "print('hello')\nprint('world')"
        chunks = chunk_code(content, "small.py", chunk_size=10, overlap=2)

        assert len(chunks) == 1
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 2
        assert chunks[0].content == content

    @pytest.mark.parametrize("empty_input", ["", "   ", "\n\n", None])
    def test_chunk_code_empty_content(self, empty_input):
        assert chunk_code(empty_input, "empty.py") == []

    def test_chunk_code_sanitizes_invalid_parameters(self):
        content = "a\nb\nc\nd"
        # chunk_size <= 0 and overlap >= chunk_size should not cause an infinite loop
        chunks = chunk_code(content, "edge.py", chunk_size=-1, overlap=100)
        assert len(chunks) > 0


# ==============================================================================
# Indexing & Exclusion Tests
# ==============================================================================


@pytest.fixture
def memory_qdrant():
    """In-memory Qdrant client isolated for each test."""
    client = QdrantClient(":memory:")
    ensure_collection(client, collection_name="code_chunks", vector_size=EMBEDDING_DIMENSION)
    return client


@pytest.fixture
def mock_embedding():
    """Deterministic dummy embedding vector matching EMBEDDING_DIMENSION."""
    dummy_vec = [0.1] * EMBEDDING_DIMENSION
    with patch("app.rag.indexer.create_embedding", return_value=dummy_vec) as mocked_emb:
        yield mocked_emb


class TestIndexingAndExclusions:
    def test_index_file_creates_points_with_line_metadata(self, tmp_path, memory_qdrant, mock_embedding, monkeypatch):
        monkeypatch.setattr("app.rag.indexer.PROJECT_ROOT", tmp_path)
        test_file = tmp_path / "service.py"
        test_file.write_text("def a(): pass\ndef b(): pass\ndef c(): pass\n", encoding="utf-8")

        count = index_file(test_file, client=memory_qdrant)
        assert count > 0

        points, _ = memory_qdrant.scroll("code_chunks", limit=10)
        assert len(points) == count
        payload = points[0].payload
        assert payload["file_path"] == "service.py"
        assert payload["start_line"] == 1
        assert "end_line" in payload
        assert "content" in payload
        assert "chunk_index" in payload

    def test_index_file_idempotency_prevents_duplicate_chunks(self, tmp_path, memory_qdrant, mock_embedding, monkeypatch):
        monkeypatch.setattr("app.rag.indexer.PROJECT_ROOT", tmp_path)
        test_file = tmp_path / "module.py"
        test_file.write_text("class Module:\n    pass\n", encoding="utf-8")

        # First index run
        count_first = index_file(test_file, client=memory_qdrant)
        points_first, _ = memory_qdrant.scroll("code_chunks", limit=50)
        assert len(points_first) == count_first

        # Second index run with updated content
        test_file.write_text("class Module:\n    name = 'updated'\n", encoding="utf-8")
        count_second = index_file(test_file, client=memory_qdrant)
        points_second, _ = memory_qdrant.scroll("code_chunks", limit=50)

        # Total points should match count_second, not count_first + count_second
        assert len(points_second) == count_second
        assert points_second[0].payload["content"] == "class Module:\n    name = 'updated'"

    def test_index_repository_respects_ignored_and_sensitive_exclusions(
        self, tmp_path, memory_qdrant, mock_embedding, monkeypatch
    ):
        monkeypatch.setattr("app.rag.indexer.PROJECT_ROOT", tmp_path)

        # 1. Regular code file (should be indexed)
        code_file = tmp_path / "app.py"
        code_file.write_text("def run(): pass\n", encoding="utf-8")

        # 2. Ignored directory file (should be skipped)
        for ignored in IGNORED_DIRS:
            ignored_folder = tmp_path / ignored
            ignored_folder.mkdir(exist_ok=True)
            (ignored_folder / "script.py").write_text("def secret(): pass\n", encoding="utf-8")

        # 3. Sensitive files (should be skipped)
        for sensitive in SENSITIVE_FILES:
            (tmp_path / sensitive).write_text("API_KEY=12345\n", encoding="utf-8")

        # 4. Non-code unsupported extension (should be skipped)
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        total = index_repository(client=memory_qdrant)
        assert total == 1

        points, _ = memory_qdrant.scroll("code_chunks", limit=50)
        indexed_files = {p.payload["file_path"] for p in points}
        assert indexed_files == {"app.py"}


# ==============================================================================
# Retrieval Tests
# ==============================================================================


class TestRetrieval:
    @pytest.mark.parametrize("empty_query", ["", "   ", "\t\n", None])
    def test_search_code_semantic_empty_query(self, memory_qdrant, empty_query):
        results = search_code_semantic(empty_query, client=memory_qdrant)
        assert results == []

    def test_search_code_semantic_returns_rich_metadata(self, tmp_path, memory_qdrant, mock_embedding, monkeypatch):
        monkeypatch.setattr("app.rag.indexer.PROJECT_ROOT", tmp_path)
        file_path = tmp_path / "auth.py"
        file_path.write_text("def login():\n    return 'authenticated'\n", encoding="utf-8")

        index_file(file_path, client=memory_qdrant)

        with patch("app.rag.retriever.create_embedding", return_value=[0.1] * EMBEDDING_DIMENSION):
            results = search_code_semantic("how to authenticate user", limit=2, client=memory_qdrant)

        assert len(results) == 1
        item = results[0]
        assert isinstance(item, SemanticSearchResult)
        # Verify both object and dictionary key access
        assert item.file_path == "auth.py"
        assert item["file_path"] == "auth.py"
        assert item.start_line == 1
        assert item["start_line"] == 1
        assert item.end_line == 2
        assert item["end_line"] == 2
        assert "login" in item.content
        assert item.score > 0
        assert item.payload["file_path"] == "auth.py"

    def test_search_code_semantic_handles_client_errors_gracefully(self):
        failing_client = MagicMock()
        failing_client.query_points.side_effect = Exception("Qdrant connection error")

        with patch("app.rag.retriever.create_embedding", return_value=[0.1] * EMBEDDING_DIMENSION):
            results = search_code_semantic("query", client=failing_client)

        assert results == []
