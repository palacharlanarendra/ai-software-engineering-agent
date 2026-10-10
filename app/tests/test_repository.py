import os
from pathlib import Path
from unittest.mock import patch
import pytest

from app.config import IGNORED_DIRS, SENSITIVE_FILES
from app.tools.repository import list_files, read_file, search_code


@pytest.fixture
def repo_dir(tmp_path, monkeypatch):
    """
    Sets up a realistic mock repository structure and monkeypatches
    PROJECT_ROOT in app.tools.repository to point to the isolated temp directory.
    """
    monkeypatch.setattr("app.tools.repository.PROJECT_ROOT", tmp_path)

    # Regular files
    (tmp_path / "main.py").write_text("def main():\n    print('Hello World')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Test Repository\nWelcome to the project.\n", encoding="utf-8")

    # Subdirectories with files
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("def run():\n    return 'Hello from app'\n", encoding="utf-8")
    (src_dir / "utils.py").write_text("# Utility functions\npass\n", encoding="utf-8")

    nested_dir = src_dir / "components"
    nested_dir.mkdir()
    (nested_dir / "button.py").write_text("class Button:\n    pass\n", encoding="utf-8")

    # Ignored directories
    for ignored in IGNORED_DIRS:
        ignored_folder = tmp_path / ignored
        ignored_folder.mkdir(exist_ok=True)
        (ignored_folder / "file.txt").write_text("ignored file content\nHello inside ignored", encoding="utf-8")

    # Sensitive files in root and subdirectories
    for sensitive in SENSITIVE_FILES:
        (tmp_path / sensitive).write_text("SECRET_KEY=12345\nHello sensitive", encoding="utf-8")
        (src_dir / sensitive).write_text("NESTED_SECRET=67890\nHello sensitive nested", encoding="utf-8")

    return tmp_path


# ==============================================================================
# list_files tests
# ==============================================================================


class TestListFiles:
    def test_list_files_includes_regular_and_nested_files(self, repo_dir):
        files = list_files()

        assert "main.py" in files
        assert "README.md" in files
        assert "src/app.py" in files
        assert "src/utils.py" in files
        assert "src/components/button.py" in files

    def test_list_files_returns_sorted_list(self, repo_dir):
        files = list_files()
        assert files == sorted(files)

    def test_list_files_excludes_ignored_directories(self, repo_dir):
        files = list_files()

        for file_path in files:
            parts = Path(file_path).parts
            assert not any(ignored in parts for ignored in IGNORED_DIRS), f"Ignored directory found in {file_path}"

    def test_list_files_excludes_sensitive_files(self, repo_dir):
        files = list_files()

        for file_path in files:
            file_name = Path(file_path).name
            assert file_name not in SENSITIVE_FILES, f"Sensitive file included: {file_path}"

    def test_list_files_excludes_directories_themselves(self, repo_dir):
        files = list_files()

        # "src" and "src/components" are directories, they must not appear in the file list
        assert "src" not in files
        assert "src/components" not in files

    def test_list_files_empty_repo(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.tools.repository.PROJECT_ROOT", tmp_path)
        assert list_files() == []


# ==============================================================================
# read_file tests
# ==============================================================================


class TestReadFile:
    def test_read_file_success(self, repo_dir):
        content = read_file("main.py")
        assert content == "def main():\n    print('Hello World')\n"

    def test_read_file_nested_path(self, repo_dir):
        content = read_file("src/app.py")
        assert content == "def run():\n    return 'Hello from app'\n"

    def test_read_file_not_found(self, repo_dir):
        result = read_file("nonexistent_file.py")
        assert result == "file not found: nonexistent_file.py"

    def test_read_file_when_target_is_directory(self, repo_dir):
        result = read_file("src")
        assert result == "Not a file: src"

    def test_read_file_directory_traversal_access_denied(self, repo_dir, tmp_path):
        # Create a file outside the repository
        outside_file = tmp_path.parent / "outside_secret.txt"
        outside_file.write_text("super_secret", encoding="utf-8")

        try:
            result = read_file("../outside_secret.txt")
            assert result == "Access denied."

            deep_traversal = read_file("../../../../../etc/passwd")
            assert deep_traversal == "Access denied."
        finally:
            if outside_file.exists():
                outside_file.unlink()

    def test_read_file_root_directory_access(self, repo_dir):
        # Path resolving to the project root itself is not a file
        result = read_file(".")
        assert result == "Not a file: ."


# ==============================================================================
# search_code tests
# ==============================================================================


class TestSearchCode:
    @pytest.mark.parametrize("query", ["", "   ", "\t\n", None])
    def test_search_code_empty_or_whitespace_query(self, repo_dir, query):
        assert search_code(query) == []

    def test_search_code_case_insensitive_matching(self, repo_dir):
        # "print('Hello World')" exists in main.py, "Hello from app" in src/app.py
        results_lower = search_code("hello")
        results_upper = search_code("HELLO")
        results_mixed = search_code("HeLLo")

        assert len(results_lower) > 0
        assert results_lower == results_upper == results_mixed

    def test_search_code_result_structure(self, repo_dir):
        results = search_code("print('Hello World')")

        assert len(results) == 1
        match = results[0]
        assert match["file"] == "main.py"
        assert match["line"] == 2
        assert match["content"] == "print('Hello World')"

    def test_search_code_multiple_matches_across_files(self, repo_dir):
        # Both main.py and src/app.py have lines with 'Hello'
        results = search_code("Hello")
        files_matched = {r["file"] for r in results}

        assert "main.py" in files_matched
        assert "src/app.py" in files_matched

    def test_search_code_no_match(self, repo_dir):
        assert search_code("non_existent_query_xyz123") == []

    def test_search_code_skips_ignored_directories(self, repo_dir):
        # Ignored files have "Hello inside ignored", should not be found
        results = search_code("Hello inside ignored")
        assert results == []

    def test_search_code_skips_sensitive_files(self, repo_dir):
        # Sensitive files have "Hello sensitive", should not be found
        results = search_code("Hello sensitive")
        assert results == []

    def test_search_code_skips_files_exceeding_max_size(self, repo_dir):
        large_file = repo_dir / "large.py"
        # max_file_size is 1_000_000 bytes
        content = "unique_large_token = 42\n" + ("#" * (1_000_000 + 10))
        large_file.write_text(content, encoding="utf-8")

        assert search_code("unique_large_token") == []

    def test_search_code_limits_results_to_max_results(self, repo_dir):
        # Generate a file with 60 matching lines
        many_matches_file = repo_dir / "many_matches.py"
        many_matches_file.write_text("\n".join(f"needle_{i}" for i in range(60)), encoding="utf-8")

        results = search_code("needle_")
        assert len(results) == 50

    def test_search_code_handles_oserror_gracefully(self, repo_dir):
        # If read_text throws OSError, it should skip the file and not crash
        with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            results = search_code("main")
            assert results == []


# ==============================================================================
# Integration smoke tests
# ==============================================================================


class TestRepositoryIntegration:
    def test_real_repo_list_files(self):
        """Smoke test verifying list_files executes against the real project root without errors."""
        files = list_files()
        assert isinstance(files, list)
        assert len(files) > 0
        assert "app/tools/repository.py" in files
        assert not any(".git" in f.split("/") for f in files)
        assert not any(f.endswith(".env") for f in files)
