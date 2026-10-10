# AI Software Engineering Agent (Version 3)

A secure, testable, backend-first AI Software Engineering Agent built with **FastAPI**, **LangGraph**, **Gemini**, **Qdrant**, and **Pytest**.

The agent investigates coding tasks using semantic repository search and retrieved evidence, produces structured diagnoses and code patches, requires explicit human approval before touching the disk, and runs constrained automated tests to verify approved fixes.

---

## 1. System Architecture

```text
                      [User Task Intake]
                              │
                              ▼
                     [1. validate_input]
                              │
                              ▼
                    [2. retrieve_context] ◄─── (Qdrant semantic search / 3072 dims)
                              │
                              ▼
                    [3. analyze_evidence] ◄─── (Gemini with structured evidence)
                              │
                              ▼
                     [4. propose_patch]   ───► (Unified diff & SHA256 checksums)
                              │
                              ▼
             ===================================
             [5. HUMAN APPROVAL GATE: INTERRUPT]
             ===================================
               (Halts workflow before file write)
                              │
                 ┌────────────┴────────────┐
              Approved                  Rejected
                 │                         │
                 ▼                         ▼
          [6. apply_patch]        [handle_rejection] ──► [END]
                 │
                 ▼
          [7. verify_patch] ◄───── (Constrained pytest execution)
                 │
            ┌────┴─────────────────┐
         Passed                  Failed
            │                      │
            ▼                      ▼
          [END]          [rollback_and_retry] ──► [analyze_evidence]
                                   │ (Exhausted retries)
                                   ▼
                         [rollback_and_fail]  ──► [END]
```

---

## 2. Directory Structure

```text
├── app/
│   ├── config.py             # Centralized settings (PROJECT_ROOT, models, Qdrant)
│   ├── logger.py             # Structured logging with secret redaction filter
│   ├── main.py               # Thin FastAPI routes and custom exception handlers
│   ├── schemas.py            # Pydantic request, response, and error models
│   ├── requirements.txt      # Pinned environment dependencies
│   ├── agent/                # LangGraph Orchestration & Workflows
│   │   ├── agent.py          # Workflow runner & resume APIs
│   │   ├── graph.py          # StateGraph definition, routing, interrupts & checkpointer
│   │   ├── nodes.py          # Explicit, isolated graph nodes
│   │   ├── patch.py          # Diff generation, syntax check, safe write, and rollback
│   │   ├── service.py        # Thin API service layer decoupling routes from graph state
│   │   ├── state.py          # Typed AgentState, PatchProposal, VerificationResult
│   │   ├── tools.py          # LangChain tools for repository inspection
│   │   └── verifier.py       # Constrained pytest verification runner
│   ├── ai/                   # LLM & Analysis Layer
│   │   ├── analyzer.py       # Code task diagnosis service with structured outputs
│   │   ├── embeddings.py     # Gemini embedding service (models/gemini-embedding-001)
│   │   ├── llm.py            # Centralized ChatGoogleGenerativeAI factory
│   │   └── schemas.py        # Pydantic schemas (evidence, hypotheses, proposed changes)
│   ├── rag/                  # Retrieval-Augmented Generation & Vector Storage
│   │   ├── chunker.py        # Line-aware code chunking (start_line, end_line)
│   │   ├── indexer.py        # Idempotent repository code indexer with exclusions
│   │   ├── retriever.py      # Qdrant semantic search returning SemanticSearchResult
│   │   └── vector_store.py   # Qdrant client factory and collection initialization
│   ├── tools/                # Repository Filesystem Tools
│   │   └── repository.py     # list_files, read_file (path-safe), search_code (case-insensitive)
│   └── tests/                # Automated Pytest Suite (104 passing tests, 92% coverage)
│       ├── test_ai_layer.py  # Mocked unit tests for LLM & analyzer
│       ├── test_api.py       # FastAPI endpoint tests (task lifecycle, proposal inspection & approval)
│       ├── test_graph.py     # LangGraph routing, patch safety, verifier bounds, rollbacks & interrupts
│       ├── test_logger.py    # Unit tests for secret redacting and log sanitation
│       ├── test_rag.py       # Chunking, indexing, and retrieval tests
│       └── test_repository.py# Traversal bounds, search, and list tests
├── scripts/                  # CLI & Helper Scripts
│   ├── index_repository.py   # CLI runner to index repository into Qdrant
│   ├── portfolio_demo.py     # Interactive end-to-end portfolio demonstration
│   ├── run_retreiver.py      # CLI runner for semantic search
│   └── run_chunker.py        # Chunking demonstration runner
├── pytest.ini                # Pytest configuration
├── requirements.txt          # Root reference to app/requirements.txt
└── .gitignore                # Excludes secrets, cache, virtualenvs, and builds
```

---

## 3. Getting Started

### Prerequisites
- Python 3.11+
- A Google Gemini API Key
- Qdrant running locally via Docker or native binary:
  ```bash
  docker run -d -p 6333:6333 -p 6334:6334 qdrant/qdrant
  ```

### Setup Environment
```bash
python -m venv my-ai-env
source my-ai-env/bin/activate
pip install -r requirements.txt
```

---

## 4. Environment Variables

Create a `.env` file in the project root:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `GEMINI_API_KEY` | String | **Required** | Google Gemini API key used for embeddings and reasoning |
| `QDRANT_URL` | String | `http://localhost:6333` | Host URL for Qdrant vector database |
| `QDRANT_COLLECTION`| String | `code_chunks` | Name of the Qdrant vector collection |
| `EMBEDDING_MODEL` | String | `models/gemini-embedding-001` | Verified embedding model with 3072 dimensions |
| `EMBEDDING_DIMENSION`| Integer| `3072` | Vector embedding dimension |
| `LLM_MODEL` | String | `gemini-2.5-flash` | LLM model for diagnosis and code repair |
| `LLM_TEMPERATURE` | Float | `0.0` | Sampling temperature (0.0 for deterministic output) |
| `LLM_TIMEOUT` | Integer| `60` | Request timeout in seconds |
| `LLM_MAX_RETRIES` | Integer| `2` | Maximum retry attempts for transient API errors |

---

## 5. Running Tests & Evaluation

The test suite runs hermetically with 100% mocked isolation for external APIs:

```bash
# Run all 104 unit and integration tests:
pytest -v

# Run test coverage report (92% total coverage):
pytest --cov=app --cov-report=term-missing
```

### Coverage Highlights:
- `app/main.py`: **100%**
- `app/schemas.py`: **100%**
- `app/agent/state.py`: **100%**
- `app/rag/retriever.py`: **100%**
- `app/tools/repository.py`: **100%**
- `app/agent/service.py`: **97%**
- `app/rag/chunker.py`: **97%**
- `app/agent/graph.py`: **94%**

---

## 6. Running the Application

### 1. Index the Repository into Qdrant
```bash
python scripts/index_repository.py
```

### 2. Start the FastAPI Dev Server
```bash
uvicorn app.main:app --reload --port 8000
```

### 3. API Documentation
- Interactive Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON Schema: `http://localhost:8000/openapi.json`

---

## 7. HTTP API Reference & Curl Examples

### Health Check
```bash
curl -s http://localhost:8000/health
```
```json
{
  "status": "ok",
  "service": "AI Software Engineering Agent",
  "version": "3.0.0",
  "qdrant_connected": true,
  "llm_configured": true
}
```

### Direct Agent Query (Chat)
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is repository path traversal handled?"}'
```

### Submit a Coding Task
```bash
curl -s -X POST http://localhost:8000/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Update the docstring of list_files in app/tools/repository.py",
    "thread_id": "session-demo-1"
  }'
```
Response (`201 Created`):
```json
{
  "thread_id": "session-demo-1",
  "task": "Update the docstring of list_files in app/tools/repository.py",
  "status": "awaiting_approval",
  "approval_status": "pending",
  "next_nodes": ["apply_patch"],
  "patch_applied": false,
  "patch": {
    "patch_id": "patch-07ee9108d073",
    "file_path": "app/tools/repository.py",
    "description": "Update docstring of list_files",
    "diff": "--- a/app/tools/repository.py\n+++ b/app/tools/repository.py\n...",
    "expected_original_checksum": "6c8402a8e552a2ab",
    "proposed_checksum": "ba4e7c92071cd531"
  }
}
```

### Inspect Pending Proposal
```bash
curl -s http://localhost:8000/task/session-demo-1/proposal
```

### Approve and Apply Patch
```bash
curl -s -X POST http://localhost:8000/task/session-demo-1/approve \
  -H "Content-Type: application/json" \
  -d '{
    "approved": true,
    "patch_id": "patch-07ee9108d073",
    "human_feedback": "Approved after reviewing diff"
  }'
```

### Reject Patch
```bash
curl -s -X POST http://localhost:8000/task/session-demo-1/approve \
  -H "Content-Type: application/json" \
  -d '{
    "approved": false,
    "human_feedback": "Diff modifies unrelated function"
  }'
```

### Standard Error Response Format
All errors return consistent envelopes with status codes:
```json
{
  "detail": "Task with thread_id 'invalid-id' not found.",
  "error_code": "NOT_FOUND"
}
```

---

## 8. Controlled Code Repair & Security Rules

The agent enforces strict safety boundaries designed to prevent accidental regressions, malicious payloads, and unauthorized modifications:

1. **Structured Patch Format**: Every proposed code change includes the target relative file path, clean unified diff, original and proposed content, deterministic `patch_id` (SHA256 digest), and content checksums.
2. **Strict Filesystem Boundaries**:
   - Rejects absolute paths (`/etc/...`, `C:\...`).
   - Prevents path traversal (`../`) to guarantee all edits stay within `PROJECT_ROOT`.
   - Protects sensitive files (`.env`, `.env.local`, credentials, `.git`).
   - Restricts modifications to allowed extensions (`.py`, `.json`, `.yaml`, `.md`, `.toml`, etc.).
3. **Explicit Human Approval Gate**:
   - Workflows halt immediately before disk writes via LangGraph's `interrupt_before=["apply_patch"]`.
   - Approvals are cryptographically tied to the exact `patch_id`. Mismatched approvals are rejected.
4. **Pre-Write Revalidation & Concurrency Protection**:
   - Compares the file on disk against `expected_original_checksum` before applying any patch.
   - Detects concurrent edits made while human review was pending and aborts with a conflict error.
5. **Constrained Automated Verification & Shell Immunity**:
   - The LLM is never given arbitrary shell access.
   - Subprocesses run hermetically via `sys.executable -m pytest` with `shell=False`.
   - Test targets are strictly validated against CLI flag injection (`-k`, `--override-ini`), absolute paths, and traversal.
6. **Automatic Rollback & Diff Preservation**:
   - If verification tests fail after exhausting bounded retries, the file is automatically rolled back to its original state.
   - The proposed patch diff and full test outputs are preserved in state for inspection.
7. **Secure Logging**:
   - API keys (including `AIza...` patterns) and authorization bearer tokens are automatically masked via `SensitiveDataFilter`.
   - Oversized source code snippets are truncated to prevent log bloat and accidental secret leaks.

---

## 9. Portfolio Demonstration

Run the automated interactive portfolio demonstration:

```bash
python scripts/portfolio_demo.py
```

The script walks through three core scenarios:
1. **Evidence-Grounded Investigation**: Asks *"Where is repository path traversal handled?"*, retrieves relevant chunks from Qdrant, calls Gemini for structured diagnosis, and returns citations to `app/tools/repository.py` lines 30-43.
2. **Blocked Unsafe Operations**: Simulates directory traversal (`../../etc/passwd`), absolute path attempts (`/var/log/system.log`), sensitive file modifications (`.env`), unpermitted extensions (`.exe`), and test runner CLI flag injections (`-k ...; rm -rf /`), proving each is blocked before execution.
3. **Controlled Repair Lifecycle**: Generates a tamper-evident patch proposal, pauses at the human approval gate, rejects mismatched approval IDs, and demonstrates safe application and rollback.

---

## 10. Known Limitations & Production Roadmap

- **Checkpointer Persistence**: The current implementation uses LangGraph's `MemorySaver` in-memory checkpointer. For multi-worker production deployments across distributed clusters, replace with `AsyncSqliteSaver` or `PostgresSaver`.
- **Single-File Patch Scope**: The current patch proposal node generates a targeted diff for one file per iteration. Multi-file coordinated refactorings can be supported by extending the proposal node into an iterative graph loop.
- **Embedding Model Dimensions**: The collection is configured for 3072 dimensions to match `models/gemini-embedding-001`. If migrating to a different embedding provider (e.g. OpenAI `text-embedding-3-small` at 1536 dims), reconfigure `EMBEDDING_DIMENSION` and re-index the collection.
- **Qdrant Dependency**: Semantic retrieval relies on a reachable Qdrant instance. When Qdrant is unreachable, the system gracefully falls back to deterministic keyword search over the local repository.
