# AI Software Engineering Agent (Version 3)

A secure, testable, backend-first AI Software Engineering Agent built with **FastAPI**, **LangGraph**, **Gemini**, **Qdrant**, and **Pytest**.

The agent investigates coding tasks using semantic repository search and retrieved evidence, produces structured diagnoses and code patches, requires explicit human approval before touching the disk, and runs constrained automated tests to verify approved fixes.

---

## 1. System Architecture

```
                      [User Task]
                          │
                          ▼
                 [1. validate_input]
                          │
                          ▼
                [2. retrieve_context] ◄─── (Qdrant semantic search)
                          │
                          ▼
                [3. analyze_evidence] ◄─── (Gemini with structured evidence)
                          │
                          ▼
                 [4. propose_patch]   ───► (Unified diff & syntax check)
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
      [7. verify_patch] ◄───── (Runs pytest suite)
             │
        ┌────┴─────────────────┐
     Passed                  Failed
        │                      │
        ▼                      ▼
      [END]          (Bounded retry loop with test error feedback)
```

---

## 2. Directory Structure

```text
├── app/
│   ├── config.py             # Centralized settings (PROJECT_ROOT, models, Qdrant)
│   ├── main.py               # FastAPI entrypoints (/chat, /task, /task/{id}/approve)
│   ├── requirements.txt      # Pinned environment dependencies
│   ├── agent/                # LangGraph Orchestration & Workflows
│   │   ├── agent.py          # Workflow runner & resume APIs
│   │   ├── graph.py          # StateGraph definition, routing, interrupts & checkpointer
│   │   ├── nodes.py          # Explicit, isolated graph nodes
│   │   ├── patch.py          # Diff generation, syntax check, safe write, and rollback
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
│   └── tests/                # Automated Pytest Suite (81 passing tests)
│       ├── test_ai_layer.py  # Mocked unit tests for LLM & analyzer
│       ├── test_api.py       # FastAPI endpoint tests
│       ├── test_graph.py     # LangGraph routing, interrupt & resume tests
│       ├── test_rag.py       # Chunking, indexing, and retrieval tests
│       └── test_repository.py# Traversal bounds, search, and list tests
├── scripts/                  # CLI & Helper Scripts
│   ├── index_repository.py   # CLI runner to index repository into Qdrant
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

### Setup Environment
```bash
python -m venv my-ai-env
source my-ai-env/bin/activate
pip install -r requirements.txt
```

### Configuration
Create a `.env` file in the project root:
```env
GEMINI_API_KEY=your_gemini_api_key_here
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=code_chunks
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSION=3072
LLM_MODEL=gemini-2.5-flash
LLM_TEMPERATURE=0.0
LLM_TIMEOUT=60
```

---

## 4. Running Tests

Run the full automated test suite (all 81 tests execute hermetically in ~1.5s):

```bash
pytest -v
```

Run test coverage report:
```bash
pytest --cov=app
```

---

## 5. Running the Application

### Index the Repository
```bash
python scripts/index_repository.py
```

### Start the FastAPI Server
```bash
uvicorn app.main:app --reload --port 8000
```

### Endpoints:
- `GET /`: Health check.
- `POST /chat`: Simple question-and-answer using the agent.
- `POST /task`: Starts a full engineering task workflow. Halts at the approval gate if code modifications are proposed.
- `GET /task/{thread_id}`: Inspects current state and next scheduled node of a task.
- `POST /task/{thread_id}/approve`: Submits `{"approved": true}` or `{"approved": false}` to resume the workflow, apply the patch, and execute automated test verification.
