#!/usr/bin/env python3
"""
Portfolio Demonstration Script: AI Software Engineering Agent (Version 3)

This script demonstrates two essential core capabilities of the agent:
1. A successful, evidence-grounded code investigation with semantic retrieval & Gemini analysis.
2. A blocked unsafe operation attempting directory traversal, sensitive file tampering, and CLI injection.
3. The controlled repair lifecycle: patch proposal, human approval gate, and rollback on failure.
"""

import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.agent import run_agent_workflow, approve_and_resume_workflow
from app.agent.patch import validate_target_path, apply_patch_safely, create_unified_diff, create_patch_id
from app.agent.verifier import run_verification_tests, validate_test_target
from app.rag.retriever import search_code_semantic


def print_banner(title: str):
    print("\n" + "=" * 80)
    print(f"  {title.upper()}")
    print("=" * 80)


def demo_successful_investigation():
    print_banner("Demo 1: Evidence-Grounded Investigation")
    query = "Where is repository path traversal handled?"
    print(f"Task: \"{query}\"\n")

    print("[Step 1] Executing Qdrant Semantic Retrieval...")
    results = search_code_semantic(query, limit=2)
    print(f"Found {len(results)} relevant chunks in vector database:")
    for r in results:
        print(f"  • {r.file_path} (lines {r.start_line}-{r.end_line}) [Score: {r.score:.3f}]")

    print("\n[Step 2] Running Agent Workflow through LangGraph...")
    state = run_agent_workflow(query)

    print(f"Workflow Status: {state.get('status')}")
    analysis = state.get("analysis") or {}
    print(f"\nDiagnosis Summary:\n{analysis.get('summary')}\n")

    evidence = analysis.get("evidence", [])
    print(f"Retrieved Evidence Citations ({len(evidence)}):")
    for ev in evidence[:2]:
        print(f"  • File: {ev.get('file_path')} (lines {ev.get('start_line')}-{ev.get('end_line')})")
        print(f"    Explanation: {ev.get('explanation')[:120]}...")

    print(f"\nProposed Code Changes: {len(analysis.get('proposed_changes', []))} (Read-only query - no code changes needed)")


def demo_blocked_unsafe_operations():
    print_banner("Demo 2: Security Boundaries & Blocked Unsafe Operations")
    print("Testing multi-layer defenses against adversarial and unpermitted operations:\n")

    attacks = [
        ("Directory Traversal", "../../etc/passwd", "Path escapes repository root"),
        ("Absolute Path", "/var/log/system.log", "Absolute system path rejected"),
        ("Sensitive File Tampering", ".env", "Modifying .env / secrets forbidden"),
        ("Unpermitted File Extension", "malicious_payload.sh.exe", "Executable extension rejected"),
        ("Test Runner Flag Injection", "-k test_foo; rm -rf /", "Arbitrary flags in test target denied"),
    ]

    for name, target, description in attacks:
        if name == "Test Runner Flag Injection":
            is_valid, err = validate_test_target(target)
            ver_res = run_verification_tests(test_target=target)
            print(f"  [ATTACK: {name}]")
            print(f"    Payload:     '{target}'")
            print(f"    Blocked:     {'YES (Access Denied)' if not is_valid else 'NO'}")
            print(f"    Safety Msg:  {ver_res.get('output')}\n")
        else:
            is_valid, _, err = validate_target_path(target)
            success, _, apply_err = apply_patch_safely(target, "malicious_content = True\n")
            print(f"  [ATTACK: {name}]")
            print(f"    Target:      '{target}' ({description})")
            print(f"    Blocked:     {'YES (Access Denied)' if not is_valid else 'NO'}")
            print(f"    Safety Msg:  {err}\n")


def demo_controlled_repair_lifecycle():
    print_banner("Demo 3: Controlled Repair Lifecycle & Human Approval Gate")

    sample_file = "app/tools/repository.py"
    print(f"Simulating repair proposal for: {sample_file}")

    # Generate synthetic patch proposal
    orig_snippet = "def list_files() -> list[str]:\n    \"\"\"List repository files.\"\"\"\n"
    prop_snippet = "def list_files() -> list[str]:\n    \"\"\"List repository files relative to root.\"\"\"\n"
    diff = create_unified_diff(orig_snippet, prop_snippet, sample_file)
    patch_id = create_patch_id(sample_file, prop_snippet)

    print(f"Generated Tamper-Evident Patch ID: {patch_id}")
    print("Unified Diff Preview:")
    for line in diff.splitlines():
        print(f"  {line}")

    print("\n[Human Approval Gate Enforcement]")
    print("1. Submitting mismatched approval ID ('patch-fake123'):")
    from app.agent.nodes import apply_patch_node
    mismatch_state = {
        "approval_status": "approved",
        "approved_patch_id": "patch-fake123",
        "patch": {"patch_id": patch_id, "file_path": sample_file, "proposed_content": prop_snippet},
        "errors": [],
    }
    mismatch_res = apply_patch_node(mismatch_state)
    print(f"   Status: {mismatch_res.get('status')} | Patch Applied: {mismatch_res.get('patch_applied')}")
    print(f"   Error:  {mismatch_res.get('errors')}")

    print("\n2. Submitting rejection feedback:")
    from app.agent.graph import handle_rejection_node
    reject_res = handle_rejection_node({"patch": {"patch_id": patch_id}})
    print(f"   Status: {reject_res.get('status')} | Patch Applied: {reject_res.get('patch_applied')}")


def main():
    print("\n" + "#" * 80)
    print("#  AI SOFTWARE ENGINEERING AGENT — PORTFOLIO DEMONSTRATION")
    print("#" * 80)

    demo_successful_investigation()
    demo_blocked_unsafe_operations()
    demo_controlled_repair_lifecycle()

    print("\n" + "#" * 80)
    print("#  DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("#" * 80 + "\n")


if __name__ == "__main__":
    main()
