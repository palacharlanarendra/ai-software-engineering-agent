import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "my-ai-env",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    "dist",
    "build",
}

SENSITIVE_FILES = {
    ".env",
    ".env.local",
    ".env.production",
}

# RAG & AI Configuration
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "code_chunks")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "3072"))
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")